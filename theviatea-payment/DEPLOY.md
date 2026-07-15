# Deploy Payment Service - TheViaTea

## Yeu cau
- Tai khoan Cloudflare (mien phi): https://dash.cloudflare.com/sign-up
- Node.js 18+

## Buoc 1: Cai dat Wrangler CLI

```bash
npm install -g wrangler
wrangler login
```

## Buoc 2: Cau hinh secrets

```bash
cd theviatea-payment

# Shopify Admin API token (tu custom app tren Shopify)
wrangler secret put SHOPIFY_ACCESS_TOKEN
# Paste: shpat_xxxxxxx (token tu Shopify Admin > Apps > Custom app)

# JWT secret (tu tao, bat ky chuoi nao du dai)
wrangler secret put JWT_SECRET
# Paste: mot-chuoi-bi-mat-bat-ky-dai-32-ky-tu
```

## Buoc 3: Deploy

```bash
npm install
npm run deploy
```

Sau khi deploy, ban se nhan duoc URL:
`https://pay-theviatea.<your-account>.workers.dev`

## Buoc 4: Cap nhat WORKER_URL

Sua file `wrangler.toml`, them vao [vars]:
```toml
[vars]
SHOPIFY_STORE = "theviatea.myshopify.com"
ALLOWED_ORIGIN = "https://theviatea.com"
WORKER_URL = "https://pay-theviatea.<your-account>.workers.dev"
```

Deploy lai:
```bash
npm run deploy
```

## Buoc 5: Cap nhat Shopify Theme

Vao Shopify Admin > Online Store > Themes > Edit Code:

### 5a. Sua `config/settings_data.json`
Tim `api_prod_url` va doi thanh URL worker moi:
```json
"api_prod_url": "https://pay-theviatea.<your-account>.workers.dev"
```

### 5b. Sua `assets/cart.js`
Tim doan code o ham checkCart(), thay:
```js
window.location.href = '/checkout';
```
Bang:
```js
fetch('/cart.js')
  .then(function(r) { return r.json(); })
  .then(function(cart) {
    return fetch('https://pay-theviatea.<your-account>.workers.dev/api/start-checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: cart.items, total_price: cart.total_price })
    });
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    window.location.href = 'https://pay-theviatea.<your-account>.workers.dev' + data.redirect;
  })
  .catch(function(err) {
    alert('Loi ket noi. Vui long thu lai.');
  });
```

## Buoc 6: (Tuy chon) Custom domain

Neu muon dung lai domain `pay.theviatea.com`:
1. Vao Cloudflare Dashboard > Workers > pay-theviatea > Settings > Triggers
2. Them Custom Domain: `pay.theviatea.com`
3. Cap nhat DNS record cho `pay.theviatea.com` tro ve Cloudflare

## Buoc 7: Test

1. Vao theviatea.com
2. Them san pham vao gio hang
3. Bam "Mua Hang"
4. Se redirect sang trang thanh toan moi
5. Dien thong tin > Hien QR code
6. Chuyen khoan theo QR
7. Sepay tu dong xac nhan don hang tren Shopify

## Luu y

- Shopify custom app can co scope: `write_orders`, `read_orders`
- Cloudflare Workers free tier: 100,000 requests/ngay (du cho hau het cac shop)
- Sepay integration van hoat dong binh thuong - webhook tu dong xac nhan don hang
