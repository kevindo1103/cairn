const SHOPIFY_API_VERSION = '2024-10';
const BANK = { account: '918668899', name: 'MBBank', holder: 'CONG TY CO PHAN THE VIA' };
const PAYMENT_PREFIX = 'DH';

// ── Crypto helpers ──────────────────────────────────────────────

async function createToken(payload, secret) {
  const data = btoa(unescape(encodeURIComponent(JSON.stringify({ ...payload, exp: Date.now() + 3600000 }))));
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(sig)));
  return data + '.' + sigB64;
}

async function verifyToken(token, secret) {
  const parts = token.split('.');
  if (parts.length !== 2) throw new Error('Invalid token format');
  const [data, sig] = parts;
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify']);
  const sigBytes = Uint8Array.from(atob(sig), c => c.charCodeAt(0));
  const valid = await crypto.subtle.verify('HMAC', key, sigBytes, new TextEncoder().encode(data));
  if (!valid) throw new Error('Invalid token');
  const payload = JSON.parse(decodeURIComponent(escape(atob(data))));
  if (payload.exp < Date.now()) throw new Error('Token expired');
  return payload;
}

// ── Shopify API ─────────────────────────────────────────────────

async function shopifyAPI(env, method, endpoint, body) {
  const res = await fetch(`https://${env.SHOPIFY_STORE}/admin/api/${SHOPIFY_API_VERSION}${endpoint}`, {
    method,
    headers: { 'X-Shopify-Access-Token': env.SHOPIFY_ACCESS_TOKEN, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`Shopify ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── CORS ────────────────────────────────────────────────────────

function corsHeaders(env) {
  return {
    'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN || '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function jsonResponse(data, env, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders(env), 'Content-Type': 'application/json' },
  });
}

// ── POST /api/start-checkout ────────────────────────────────────

async function handleStartCheckout(request, env) {
  const body = await request.json();
  const items = (body.items || []).map(i => ({
    variant_id: i.variant_id || i.id,
    quantity: i.quantity,
    title: i.title || i.product_title || '',
    price: i.price || i.line_price || 0,
    image: i.image || i.featured_image?.url || '',
  }));
  const totalPrice = body.total_price || items.reduce((s, i) => s + i.price * i.quantity, 0);

  const token = await createToken({ items, total_price: totalPrice }, env.JWT_SECRET);
  return jsonResponse({ redirect: `/pay?token=${encodeURIComponent(token)}` }, env);
}

// ── GET /pay?token=xxx ──────────────────────────────────────────

async function handlePaymentPage(url, env) {
  const token = url.searchParams.get('token');
  if (!token) return new Response('Thieu token', { status: 400 });

  let cart;
  try {
    cart = await verifyToken(token, env.JWT_SECRET);
  } catch {
    return new Response('Phien thanh toan het han. Vui long quay lai gio hang va thu lai.', { status: 400 });
  }

  return new Response(renderPaymentHTML(cart, token, env), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

// ── POST /api/create-order ──────────────────────────────────────

async function handleCreateOrder(request, env) {
  const { token, customer } = await request.json();
  const cart = await verifyToken(token, env.JWT_SECRET);

  const lineItems = cart.items.map(i => ({ variant_id: i.variant_id, quantity: i.quantity }));

  const address = {
    first_name: customer.first_name || '',
    last_name: customer.last_name || '',
    address1: customer.address1 || '',
    city: customer.city || '',
    province: customer.province || '',
    zip: customer.zip || '',
    country: 'VN',
    phone: customer.phone || '',
  };

  const result = await shopifyAPI(env, 'POST', '/orders.json', {
    order: {
      email: customer.email,
      financial_status: 'pending',
      send_receipt: true,
      line_items: lineItems,
      shipping_address: address,
      billing_address: address,
      shipping_lines: [{ title: 'Standard', price: '0.00', code: 'Standard' }],
      tags: 'sepay-qr,chuyen-khoan',
    },
  });

  const order = result.order;
  const totalVND = Math.round(parseFloat(order.total_price));
  const content = PAYMENT_PREFIX + order.order_number;

  return jsonResponse({
    order_id: order.id,
    order_number: order.order_number,
    order_name: order.name,
    total_price: totalVND,
    content,
    qr_url: `https://qr.sepay.vn/img?acc=${BANK.account}&bank=${BANK.name}&amount=${totalVND}&des=${encodeURIComponent(content)}`,
    order_status_url: order.order_status_url || '',
  }, env);
}

// ── GET /api/status/:orderId ────────────────────────────────────

async function handleCheckStatus(url, env) {
  const orderId = url.pathname.split('/').pop();
  const result = await shopifyAPI(env, 'GET', `/orders/${orderId}.json?fields=id,financial_status,order_status_url`);
  return jsonResponse({
    paid: result.order.financial_status === 'paid',
    financial_status: result.order.financial_status,
    order_status_url: result.order.order_status_url || '',
  }, env);
}

// ── HTML ────────────────────────────────────────────────────────

function escapeHTML(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatVND(cents) {
  const vnd = Math.round(cents / 100);
  return vnd.toLocaleString('vi-VN');
}

function renderPaymentHTML(cart, token, env) {
  const totalDisplay = formatVND(cart.total_price);

  const itemsHTML = cart.items.map(i => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #eee">
      <div style="flex:1">
        <div style="font-weight:500">${escapeHTML(i.title)}</div>
        <div style="color:#666;font-size:14px">x${i.quantity}</div>
      </div>
      <div style="font-weight:600">${formatVND(i.price * i.quantity)}d</div>
    </div>`).join('');

  const workerOrigin = env.WORKER_URL || '';

  return `<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Thanh toan - TheViaTea</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#f5f5f5;color:#333;min-height:100vh}
.header{background:#1a1a2e;color:#fff;padding:16px 24px;text-align:center}
.header h1{font-size:20px;font-weight:400;letter-spacing:2px}
.container{max-width:960px;margin:0 auto;padding:24px 16px;display:grid;grid-template-columns:1fr;gap:24px}
@media(min-width:768px){.container{grid-template-columns:1fr 1fr}}
.card{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
.card h2{font-size:18px;margin-bottom:16px;color:#1a1a2e}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:14px;font-weight:500;margin-bottom:6px;color:#555}
.form-group input{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:15px;transition:border-color .2s}
.form-group input:focus{outline:none;border-color:#0d9e6d}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.btn{width:100%;padding:14px;background:#0d9e6d;color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:600;cursor:pointer;transition:background .2s;margin-top:8px}
.btn:hover{background:#0b8a5e}
.btn:disabled{background:#ccc;cursor:not-allowed}
.total-row{display:flex;justify-content:space-between;padding:12px 0;font-size:18px;font-weight:700;border-top:2px solid #333;margin-top:8px}
.qr-box{text-align:center;padding:24px;background:#f0faf6;border-radius:12px;border:2px solid #0d9e6d}
.qr-box img{width:220px;height:220px;margin:16px auto;display:block;border-radius:8px}
.bank-info{text-align:left;margin-top:16px}
.bank-info tr td{padding:6px 8px;font-size:14px}
.bank-info tr td:first-child{color:#666}
.bank-info tr td:last-child{font-weight:600}
.status-msg{text-align:center;padding:16px;border-radius:8px;margin-top:16px;font-size:15px}
.status-pending{background:#fff3cd;color:#856404}
.status-paid{background:#d4edda;color:#155724}
.step{display:none}.step.active{display:block}
.error{color:#e74c3c;font-size:14px;margin-top:8px}
</style>
</head>
<body>

<div class="header">
  <h1>THEVIA TEA</h1>
</div>

<div class="container">
  <!-- Left: Form / QR -->
  <div>
    <!-- Step 1: Customer info -->
    <div id="step1" class="card step active">
      <h2>Thong tin giao hang</h2>
      <form id="customerForm">
        <div class="form-group">
          <label>Email</label>
          <input type="email" name="email" required placeholder="email@example.com">
        </div>
        <div class="row">
          <div class="form-group">
            <label>Ho</label>
            <input type="text" name="last_name" required placeholder="Nguyen">
          </div>
          <div class="form-group">
            <label>Ten</label>
            <input type="text" name="first_name" required placeholder="Van A">
          </div>
        </div>
        <div class="form-group">
          <label>So dien thoai</label>
          <input type="tel" name="phone" required placeholder="0912345678">
        </div>
        <div class="form-group">
          <label>Dia chi</label>
          <input type="text" name="address1" required placeholder="So nha, duong">
        </div>
        <div class="row">
          <div class="form-group">
            <label>Quan/Huyen</label>
            <input type="text" name="province" placeholder="Quan Ba Dinh">
          </div>
          <div class="form-group">
            <label>Thanh pho</label>
            <input type="text" name="city" required placeholder="Ha Noi">
          </div>
        </div>
        <div id="formError" class="error" style="display:none"></div>
        <button type="submit" class="btn" id="submitBtn">Tiep tuc thanh toan</button>
      </form>
    </div>

    <!-- Step 2: QR Payment -->
    <div id="step2" class="card step">
      <div class="qr-box">
        <h2 style="color:#0d9e6d;margin-bottom:8px">Quet ma QR de thanh toan</h2>
        <p style="font-size:14px;color:#666;margin-bottom:8px">Don hang <strong id="orderName"></strong></p>
        <img id="qrImage" src="" alt="QR Code">
        <table class="bank-info" style="width:100%;margin-top:16px">
          <tr><td>Ngan hang:</td><td>${BANK.name}</td></tr>
          <tr><td>So tai khoan:</td><td>${BANK.account}</td></tr>
          <tr><td>Chu TK:</td><td>${BANK.holder}</td></tr>
          <tr><td>So tien:</td><td id="payAmount"></td></tr>
          <tr><td>Noi dung CK:</td><td id="payContent" style="color:#e74c3c"></td></tr>
        </table>
      </div>
      <div id="paymentStatus" class="status-msg status-pending" style="margin-top:16px">
        Dang cho thanh toan... Tu dong xac nhan khi nhan duoc tien.
      </div>
    </div>

    <!-- Step 3: Success -->
    <div id="step3" class="card step" style="text-align:center;padding:48px 24px">
      <div style="font-size:48px;margin-bottom:16px">&#10004;</div>
      <h2 style="color:#0d9e6d">Thanh toan thanh cong!</h2>
      <p style="margin-top:12px;color:#666">Don hang cua ban da duoc xac nhan.</p>
      <a id="orderLink" href="#" class="btn" style="display:inline-block;text-decoration:none;margin-top:24px;max-width:300px">Xem don hang</a>
    </div>
  </div>

  <!-- Right: Order summary -->
  <div class="card" style="align-self:start">
    <h2>Don hang</h2>
    ${itemsHTML}
    <div class="total-row">
      <span>Tong cong</span>
      <span>${totalDisplay}d</span>
    </div>
  </div>
</div>

<script>
const TOKEN = '${token.replace(/'/g, "\\'")}';
const API_BASE = '${workerOrigin}';

document.getElementById('customerForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const btn = document.getElementById('submitBtn');
  const errEl = document.getElementById('formError');
  btn.disabled = true;
  btn.textContent = 'Dang tao don hang...';
  errEl.style.display = 'none';

  const fd = new FormData(this);
  const customer = {};
  fd.forEach(function(v, k) { customer[k] = v; });

  try {
    const res = await fetch(API_BASE + '/api/create-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: TOKEN, customer: customer }),
    });

    if (!res.ok) {
      var errData = await res.json().catch(function() { return {}; });
      throw new Error(errData.error || 'Loi tao don hang');
    }

    var data = await res.json();
    window._orderId = data.order_id;
    window._orderStatusUrl = data.order_status_url;

    document.getElementById('qrImage').src = data.qr_url;
    document.getElementById('orderName').textContent = data.order_name;
    document.getElementById('payAmount').textContent = data.total_price.toLocaleString('vi-VN') + ' VND';
    document.getElementById('payContent').textContent = data.content;
    document.getElementById('orderLink').href = data.order_status_url || '#';

    document.getElementById('step1').classList.remove('active');
    document.getElementById('step2').classList.add('active');

    pollPayment(data.order_id);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.style.display = 'block';
    btn.disabled = false;
    btn.textContent = 'Tiep tuc thanh toan';
  }
});

function pollPayment(orderId) {
  var interval = setInterval(async function() {
    try {
      var res = await fetch(API_BASE + '/api/status/' + orderId);
      var data = await res.json();
      if (data.paid) {
        clearInterval(interval);
        document.getElementById('step2').classList.remove('active');
        document.getElementById('step3').classList.add('active');
        if (data.order_status_url) {
          document.getElementById('orderLink').href = data.order_status_url;
        }
      }
    } catch (e) {}
  }, 5000);
}
</script>

</body>
</html>`;
}

// ── Main router ─────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }

    try {
      if (url.pathname === '/api/start-checkout' && request.method === 'POST') {
        return handleStartCheckout(request, env);
      }
      if (url.pathname === '/pay' && request.method === 'GET') {
        return handlePaymentPage(url, env);
      }
      if (url.pathname === '/api/create-order' && request.method === 'POST') {
        return handleCreateOrder(request, env);
      }
      if (url.pathname.startsWith('/api/status/') && request.method === 'GET') {
        return handleCheckStatus(url, env);
      }
      return new Response('Not Found', { status: 404 });
    } catch (err) {
      return jsonResponse({ error: err.message }, env, 500);
    }
  },
};
