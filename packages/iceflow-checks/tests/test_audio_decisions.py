import copy
import io
import json
import wave
from pathlib import Path
import pytest
from iceflow_harness.audio import inspect_audio
from iceflow_harness.common import Refused, digest
from iceflow_harness.decisions import lint_decision, lint_document

@pytest.fixture
def audio(tmp_path):
    root=tmp_path/'audio'; (root/'kds-ready-v1').mkdir(parents=True)
    policy={
      'schema':'KDS_STATIC_AUDIO_V1','source':'static','locale':'vi-VN','range':{'min':1,'max':2},
      'sentence_template':'Synthetic {daily_seq}', 'generator':'test-only','generator_sha256':'a'*64,
      'model':'synthetic-only','codec':'PCM_S16LE','codec_identity':'synthetic-only',
      'voice':'test','encoding':'WAV','container':'RIFF/WAVE'
    }
    ap={'mime':'audio/wav','sample_rate':48000,'channels':1,'sample_width':2}
    source=(f'_MANIFEST_POLICIES={ {"kds-ready-v1":policy}!r}\n_ASSET_AUDIO_POLICY={ap!r}\n_ASSET_COUNT=2\n').encode()
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\x00\x00'*480)
    data=stream.getvalue()
    assets=[]
    for seq in (1,2):
        filename=f'kds-ready-v1/order-ready-{seq:04d}.wav'
        (root/filename).write_bytes(data)
        assets.append({'daily_seq':seq,'filename':filename,'sha256':digest(data),'bytes':len(data),'duration_ms':10,**ap})
    manifest={**policy,'version':'kds-ready-v1','template_sha256':digest(policy['sentence_template'].encode()),'assets':assets}
    raw=json.dumps(manifest).encode();(root/'manifest.json').write_bytes(raw)
    binding={'asset_id':'123','archive_sha256':'b'*64,'manifest_sha256':digest(raw)}
    (root/'source-identity.json').write_text(json.dumps(binding))
    return root, source, binding

def test_audio_positive(audio):
    r=inspect_audio(*audio)[0]
    assert r['status']=='PASS' and r['details']['assets']==2
    assert r['details']['http_serving_test']=='NOT_RUN'

def test_audio_null_binding_is_not_opt_out(audio):
    with pytest.raises(Refused,match='BINDING_REQUIRED'): inspect_audio(audio[0],audio[1],None)

def test_audio_manifest_missing(audio):
    (audio[0]/'manifest.json').unlink()
    with pytest.raises(Refused,match='MANIFEST_MISSING'): inspect_audio(*audio)

def test_audio_file_missing(audio):
    (audio[0]/'kds-ready-v1/order-ready-0002.wav').unlink()
    with pytest.raises(Refused,match='ASSET_MISSING'): inspect_audio(*audio)

def test_audio_corruption(audio):
    p=audio[0]/'kds-ready-v1/order-ready-0001.wav';p.write_bytes(b'corrupt')
    with pytest.raises(Refused,match='DIGEST'): inspect_audio(*audio)

def test_audio_symlink(audio):
    p=audio[0]/'kds-ready-v1/order-ready-0002.wav';p.unlink()
    try:
        p.symlink_to('order-ready-0001.wav')
    except OSError:
        pytest.fail('LINK_CAPABILITY_REQUIRED: assertion NOT_RUN; do not count as guard PASS')
    with pytest.raises(Refused,match='SYMLINK'): inspect_audio(*audio)

def test_audio_binding_mismatch(audio):
    binding=dict(audio[2],asset_id='456')
    with pytest.raises(Refused,match='BINDING_MISMATCH'): inspect_audio(audio[0],audio[1],binding)

def test_audio_no_dynamic_source_fallback(audio):
    with pytest.raises(Refused,match='POLICY_UNRESOLVED'): inspect_audio(audio[0],b'_MANIFEST_POLICIES = make_policy()',audio[2])

def decision():
    return json.loads((Path(__file__).parents[1]/'examples/decision-SYNTHETIC-ONLY.json').read_text())

def test_valid_shape_never_grants_permission():
    f=lint_decision(decision())[0]
    assert f['status']=='INFO' and f['details']['effective_permissions']==[]
    assert f['details']['identity_verified'] is False

def test_missing_nested_head_is_rejected():
    d=decision();d['subject'].pop('head_sha')
    assert lint_decision(d)[0]['status']=='FAIL'

def test_removed_grants_field_is_rejected():
    d=decision();d['grants']=['deploy']
    assert lint_decision(d)[0]['status']=='FAIL'

def test_overlap_deny_rejected():
    d=decision();d['denies'].append('edit')
    assert lint_decision(d)[0]['code']=='GRANT_DENY_CONFLICT'

def test_bad_time_rejected():
    d=decision();d['expires_at']='2026-09-27T00:00:00Z'
    assert lint_decision(d)[0]['code']=='DECISION_INVALID_TIME_RANGE'

def test_prose_never_infers_approval():
    assert lint_document('Kevin approved deploy now.')[0]['code']=='UNSTRUCTURED_NO_AUTHORITY_EXTRACTED'

def test_fenced_decision():
    text='Candidate proposal\n```decision\n'+json.dumps(decision())+'\n```\n'
    assert lint_document(text)[0]['status']=='INFO'

def test_unknown_actor_field_cannot_self_authenticate():
    d=decision();d['actor_verified']=True
    assert lint_decision(d)[0]['status']=='FAIL'
