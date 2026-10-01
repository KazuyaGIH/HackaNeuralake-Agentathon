// Smoke da interface com Playwright: projetos -> exemplo -> iniciar -> acompanhar -> resultado -> historico.
// Uso: node scripts/ui_smoke.mjs [baseUrl] [outDir]   (requer `npm i playwright` e `npx playwright install chromium`)
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const base = process.argv[2] ?? "http://127.0.0.1:3000";
const out = process.argv[3] ?? "data/ui-smoke";
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });

await page.goto(base, { waitUntil: "networkidle" });
await page.getByRole("button", { name: /Criar exemplo/ }).first().click();
await page.waitForURL(/\/projetos\//, { timeout: 15000 });
await page.waitForSelector("text=Configuração", { timeout: 15000 });
await page.screenshot({ path: `${out}/01-form.png`, fullPage: true });
await page.getByRole("button", { name: /Iniciar arena/ }).click();
await page.waitForSelector("text=Candidatos", { timeout: 15000 });
await page.screenshot({ path: `${out}/02-running.png`, fullPage: true });
await page.waitForSelector("text=Resultado", { timeout: 60000 });
await page.waitForSelector("text=Propostas lado a lado", { timeout: 60000 });
await page.screenshot({ path: `${out}/03-result.png`, fullPage: true });
// Clique em uma evidencia para abrir o painel lateral
const chip = page.locator(".chip").first();
if (await chip.count()) { await chip.click(); await page.waitForTimeout(300); }
await page.screenshot({ path: `${out}/04-evidence.png`, fullPage: false });
// Recarregar a pagina: mesmo run, sem novas chamadas
const url = page.url();
const callsBefore = await page.locator("dl.kv dd").first().innerText();
await page.reload({ waitUntil: "networkidle" });
await page.locator(".side-item.run").first().click();
await page.waitForSelector("text=Resultado", { timeout: 30000 });
const callsAfter = await page.locator("dl.kv dd").first().innerText();
await page.goto(`${base}/runs`, { waitUntil: "networkidle" });
await page.waitForSelector("table", { timeout: 15000 });
await page.screenshot({ path: `${out}/05-history.png`, fullPage: true });
const rows = await page.locator("tbody tr").count();
console.log(JSON.stringify({ ok: true, runUrl: url, callsBefore, callsAfter, historyRows: rows, errors }, null, 1));
await browser.close();
if (errors.length) process.exit(2);
