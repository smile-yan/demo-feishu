import QRCode from 'qrcode'
import './style.css'

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id)

async function api(path, { method = 'GET' } = {}) {
  const resp = await fetch(path, {
    method,
    headers: { Accept: 'application/json' },
    credentials: 'include',
  })
  let body = null
  try {
    body = await resp.json()
  } catch {
    body = null
  }
  if (!resp.ok) {
    const detail = body?.detail ?? `HTTP ${resp.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return body
}

function setStatus(el, text, kind = '') {
  el.textContent = text
  el.className = `status ${kind}`
}

function setPill(el, text, kind = '') {
  el.textContent = text
  el.className = `pill ${kind}`
}

/** refresh_token 一次性，展示完整值并缓存到 dataset 供复制。 */
function setRefreshToken(token) {
  const el = $('refresh-token')
  el.textContent = token ?? ''
  el.dataset.value = token ?? ''
  // 完整值可能很长，横向滚动展示前段
  el.classList.toggle('long', (token ?? '').length > 48)
}

/** 复制到剪贴板，并短暂反馈按钮文字。 */
async function copyText(text, btn) {
  if (!text) return
  const original = btn.textContent
  try {
    await navigator.clipboard.writeText(text)
    btn.textContent = '已复制'
  } catch {
    btn.textContent = '复制失败'
  }
  setTimeout(() => {
    btn.textContent = original
  }, 1200)
}

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------

const state = {
  appReady: false,
  loginReady: false,
  appPolling: false,
  loginPolling: false,
}

// ---------------------------------------------------------------------------
// 第 1 步：获取应用凭证
// ---------------------------------------------------------------------------

$('btn-app').addEventListener('click', beginAppRegistration)

async function beginAppRegistration() {
  const btn = $('btn-app')
  btn.disabled = true
  setPill($('pill1'), '进行中', 'busy')

  try {
    const data = await api('/api/app/begin', { method: 'POST' })
    $('uc1').textContent = data.user_code
    $('link1').href = data.verification_url
    $('qr1-wrap').hidden = false

    // 前端本地渲染二维码，后端只返回链接
    $('qr1').innerHTML = ''
    const canvas = document.createElement('canvas')
    await QRCode.toCanvas(canvas, data.verification_url, {
      width: 220,
      margin: 1,
    })
    $('qr1').appendChild(canvas)

    setStatus($('status1'), '等待扫码…（二维码有效期 ' + data.expires_in + ' 秒）')
    state.appPolling = true
    pollApp()
  } catch (err) {
    setStatus($('status1'), `失败：${err.message}`, 'err')
    setPill($('pill1'), '失败', 'err')
    btn.disabled = false
  }
}

async function pollApp() {
  if (!state.appPolling) return
  try {
    const data = await api('/api/app/poll')
    if (data.status === 'success') {
      state.appPolling = false
      onAppReady(data)
      return
    }
    if (data.status === 'slow_down') {
      setStatus($('status1'), '飞书要求降低轮询频率，继续等待…')
    }
    const wait = (data.retry_after ?? 3) * 1000
    setTimeout(pollApp, Math.max(wait, 1500))
  } catch (err) {
    state.appPolling = false
    setStatus($('status1'), `失败：${err.message}`, 'err')
    setPill($('pill1'), '失败', 'err')
    $('btn-app').disabled = false
  }
}

function onAppReady(data) {
  state.appReady = true
  setStatus($('status1'), '已获取应用凭证 ✓', 'ok')
  setPill($('pill1'), '完成', 'ok')
  $('btn-app').disabled = true
  $('btn-app').textContent = '已完成'
  $('app-id').textContent = data.app_id
  if (data.app_secret) $('app-secret').textContent = data.app_secret
  $('app-result').hidden = false
  $('qr1-wrap').hidden = true

  $('step2').classList.remove('locked')
  $('btn-login').disabled = false
}

$('btn-copy-id').addEventListener('click', (e) => {
  copyText($('app-id').textContent, e.currentTarget)
})

$('btn-copy-secret').addEventListener('click', (e) => {
  copyText($('app-secret').textContent, e.currentTarget)
})

$('btn-copy-rt').addEventListener('click', (e) => {
  copyText($('refresh-token').dataset.value ?? '', e.currentTarget)
})

// ---------------------------------------------------------------------------
// 第 2 步：用户登录授权
// ---------------------------------------------------------------------------

$('btn-login').addEventListener('click', beginLogin)

async function beginLogin() {
  const btn = $('btn-login')
  btn.disabled = true
  setPill($('pill2'), '进行中', 'busy')

  try {
    const data = await api('/api/login/begin', { method: 'POST' })
    $('uc2').textContent = data.user_code
    $('link2').href = data.verification_url
    $('qr2-wrap').hidden = false
    $('qr2').hidden = true // 默认走「浏览器点确认」，不展示二维码
    $('btn-qr2').hidden = false

    setStatus($('status2'), '等待确认授权…（有效期 ' + data.expires_in + ' 秒）')
    state.loginPolling = true
    pollLogin()
  } catch (err) {
    setStatus($('status2'), `失败：${err.message}`, 'err')
    setPill($('pill2'), '失败', 'err')
    btn.disabled = false
  }
}

/** 需要扫码时再渲染二维码（备用路径，不影响主流程）。 */
async function showLoginQR() {
  const url = $('link2').href
  const box = $('qr2')
  const btn = $('btn-qr2')
  btn.hidden = true
  if (!url || !box.hidden) return
  box.innerHTML = ''
  const canvas = document.createElement('canvas')
  await QRCode.toCanvas(canvas, url, { width: 200, margin: 1 })
  box.appendChild(canvas)
  box.hidden = false
}

$('btn-qr2').addEventListener('click', () => {
  showLoginQR().catch(() => {})
})

async function pollLogin() {
  if (!state.loginPolling) return
  try {
    const data = await api('/api/login/poll')
    if (data.status === 'success') {
      state.loginPolling = false
      onLoginReady(data)
      return
    }
    if (data.status === 'slow_down') {
      setStatus($('status2'), '飞书要求降低轮询频率，继续等待…')
    }
    const wait = (data.retry_after ?? 3) * 1000
    setTimeout(pollLogin, Math.max(wait, 1500))
  } catch (err) {
    state.loginPolling = false
    setStatus($('status2'), `失败：${err.message}`, 'err')
    setPill($('pill2'), '失败', 'err')
    $('btn-login').disabled = false
  }
}

function onLoginReady(data) {
  state.loginReady = true
  setStatus($('status2'), '登录成功 ✓', 'ok')
  setPill($('pill2'), '完成', 'ok')
  $('btn-login').disabled = true
  $('btn-login').textContent = '已完成'
  $('qr2-wrap').hidden = true

  const user = data.user ?? {}
  const name = user.name ?? user.en_name ?? '(未返回昵称)'
  const avatar = user.avatar_url ?? user.avatar_thumb ?? ''
  $('user-box').innerHTML = `
    ${avatar ? `<img src="${avatar}" alt="" />` : ''}
    <div><strong>${name}</strong>${
      user.email ? `<span class="muted">${user.email}</span>` : ''
    }</div>`

  $('open-id').textContent = user.open_id ?? '(未返回)'
  $('scopes').innerHTML = (data.scopes ?? [])
    .map((s) => `<code class="scope">${s}</code>`)
    .join('') || '<span class="muted">（空）</span>'
  setRefreshToken(data.refresh_token)
  $('login-result').hidden = false

  $('step3').classList.remove('locked')
  $('btn-me').disabled = false
  $('btn-refresh').disabled = false
}

// ---------------------------------------------------------------------------
// 第 3 步：调用飞书接口
// ---------------------------------------------------------------------------

function showApi(label, payload) {
  const out = $('api-out')
  out.hidden = false
  out.textContent = `// ${label}\n${JSON.stringify(payload, null, 2)}`
}

$('btn-me').addEventListener('click', async () => {
  const btn = $('btn-me')
  btn.disabled = true
  setStatus($('status3'), '调用中…')
  try {
    const data = await api('/api/me')
    setStatus($('status3'), '调用成功 ✓', 'ok')
    setPill($('pill3'), '完成', 'ok')
    showApi('GET /open-apis/authen/v1/user_info', data)
  } catch (err) {
    setStatus($('status3'), `失败：${err.message}`, 'err')
  } finally {
    btn.disabled = false
  }
})

$('btn-refresh').addEventListener('click', async () => {
  const btn = $('btn-refresh')
  btn.disabled = true
  setStatus($('status3'), '刷新中…')
  try {
    const data = await api('/api/refresh', { method: 'POST' })
    setStatus(
      $('status3'),
      `刷新成功 ✓ 第 ${data.refresh_count} 次，新 access_token 前缀 ${data.access_token_prefix}…`,
      'ok'
    )
    if (data.refresh_token) {
      setRefreshToken(data.refresh_token)
    }
    showApi('POST /oauth/v3/token (grant_type=refresh_token)', data)
  } catch (err) {
    setStatus($('status3'), `失败：${err.message}`, 'err')
  } finally {
    btn.disabled = false
  }
})

// ---------------------------------------------------------------------------
// 重置 / 恢复状态
// ---------------------------------------------------------------------------

$('btn-reset').addEventListener('click', async () => {
  await api('/api/reset', { method: 'POST' })
  location.reload()
})

async function restore() {
  try {
    const data = await api('/api/state')
    $('scope-hint').textContent = (data.requested_scopes ?? []).join(' ') || '(空)'

    if (data.app_source === 'env') {
      // 凭证来自 backend/.env：第 1 步无事可做，直接从第 2 步开始
      presetApp(data.app)
    } else if (data.app) {
      state.appReady = true
      onAppReady({ app_id: data.app.app_id, app_secret: data.app.app_secret })
    }

    if (data.login) {
      state.loginReady = true
      $('qr2-wrap').hidden = true
      $('btn-login').disabled = true
      $('btn-login').textContent = '已完成'
      setStatus($('status2'), '登录成功 ✓', 'ok')
      setPill($('pill2'), '完成', 'ok')
      onLoginReady({
        user: data.login.user,
        scopes: data.login.scopes,
        refresh_token: data.login.refresh_token,
      })
    }
  } catch (err) {
    console.warn('恢复状态失败', err)
  }
}

/** 预置凭证模式：第 1 步折叠成一行说明，直接从第 2 步开始。 */
function presetApp(app) {
  state.appReady = true
  setStatus($('status1'), `已读取 .env 中的凭证：${app?.app_id ?? ''}`, 'ok')
  setPill($('pill1'), '已跳过', 'ok')
  $('btn-app').disabled = true
  $('btn-app').textContent = '已跳过（使用 .env 凭证）'
  $('btn-app').hidden = true
  $('step1').classList.remove('locked')
  $('step1').querySelector('.desc').textContent =
    '已通过 backend/.env 的 LARK_APP_ID / LARK_APP_SECRET 提供应用凭证，本步跳过。' +
    '删掉这两个变量并重启后端，就会回到扫码创建/选择应用的流程。'

  $('step2').classList.remove('locked')
  $('btn-login').disabled = false
  setPill($('pill2'), '待开始', '')
}

restore()
