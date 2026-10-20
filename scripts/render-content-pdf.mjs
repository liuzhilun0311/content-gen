import fs from "node:fs";
import {pathToFileURL} from "node:url";

const [input, output, playwrightPath, browserPath] = process.argv.slice(2);
if (!input || !output || !playwrightPath) {
  throw new Error("Usage: render-content-pdf.mjs input.html output.pdf playwright-entry [browser-executable]");
}
const {chromium} = await import(pathToFileURL(playwrightPath).href);
const browser = await chromium.launch({
  headless: true,
  ...(browserPath ? {executablePath: browserPath} : {}),
});
try {
  const page = await browser.newPage();
  await page.route("**/*", route => {
    const protocol = new URL(route.request().url()).protocol;
    return ["file:", "data:", "about:"].includes(protocol) ? route.continue() : route.abort();
  });
  await page.goto(pathToFileURL(input).href, {waitUntil: "load"});
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(image => image.decode()));
    if ([...document.images].some(image => !image.naturalWidth)) throw new Error("Image failed to load");
  });
  await page.pdf({
    path: output, format: "A4", printBackground: true, tagged: true, outline: true,
    margin: {top: "18mm", bottom: "20mm", left: "22mm", right: "22mm"},
    displayHeaderFooter: true, headerTemplate: "<span></span>",
    footerTemplate: '<div style="font-size:9px;width:100%;text-align:center;color:#666"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
  });
  if (!fs.statSync(output).size) throw new Error("PDF is empty");
} finally {
  await browser.close();
}
