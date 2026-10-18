// Screenshot + smoke-check harness. Drives the installed Chrome via CDP.
// Usage: node scripts/screenshot.mjs <url> <out.png> [--set-alpha 0|1] [--check]
import puppeteer from 'puppeteer-core'

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const [url, out] = process.argv.slice(2)
const alphaIdx = process.argv.indexOf('--set-alpha')
const setAlpha = alphaIdx >= 0 ? Number(process.argv[alphaIdx + 1]) : null
const check = process.argv.includes('--check')

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--window-size=1440,2000'],
})
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 2000 })

const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text())
})
page.on('pageerror', (e) => errors.push(String(e)))

await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 })
// wait for the schedule to render (KPI tag present)
await page.waitForFunction(() => document.body.innerText.includes('SIMULATED SAVINGS'), {
  timeout: 15000,
})
await new Promise((r) => setTimeout(r, 1200))

if (setAlpha !== null) {
  await page.evaluate((a) => {
    const slider = document.querySelector('input[type="range"]')
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    setter.call(slider, String(a))
    slider.dispatchEvent(new Event('input', { bubbles: true }))
    slider.dispatchEvent(new Event('change', { bubbles: true }))
  }, setAlpha)
  await page.waitForFunction(
    (a) => document.body.innerText.includes(`α = ${a.toFixed(2)}`),
    { timeout: 10000 },
    setAlpha,
  )
  // debounce 250 ms + optimize round trip
  await new Promise((r) => setTimeout(r, 1600))
}

await page.screenshot({ path: out, fullPage: true })
const status = await page.evaluate(() => ({
  banner: document.body.innerText.includes('Backend unreachable'),
  alpha: /α = ([0-9.]+)/.exec(document.body.innerText)?.[1],
  badges: [...document.querySelectorAll('header span')].map((s) => s.textContent),
  feed: document.body.innerText.includes('live stream')
    ? 'sse'
    : document.body.innerText.includes('polling 2s')
      ? 'poll'
      : 'none',
}))
console.log(JSON.stringify({ status, consoleErrors: errors }, null, 2))
await browser.close()
if (check && errors.length > 0) process.exit(1)
