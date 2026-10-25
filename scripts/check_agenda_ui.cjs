const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");
const { PNG } = require("pngjs");

(async () => {
  const base = process.env.AGENDA_PREVIEW_URL || "http://127.0.0.1:8971";
  const output = path.resolve(".pytest_cache/agenda-visual");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}),
  });
  const errors = [];
  try {
    for (const [width, height] of [[390, 844], [320, 740], [768, 1024], [1440, 1000]]) {
      const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
      page.on("pageerror", error => errors.push(error.message));
      page.on("requestfailed", request => errors.push(request.url() + ": " + request.failure().errorText));
      page.on("response", response => {
        if (response.status() >= 400 && !response.url().endsWith("/expired")) {
          errors.push(response.status() + " " + response.url());
        }
      });
      page.on("request", request => assert.ok(request.url().startsWith(base), "No external assets"));
      await page.goto(base);
      await page.evaluate(() => document.fonts.ready);
      assert.equal(await page.locator("h1").innerText(), "Agenda");
      assert.equal(await page.getByRole("tab").count(), 7);
      assert.equal(await page.getByRole("tabpanel").count(), 1);
      const fonts = await page.evaluate(() =>
        [...document.fonts].map(font => ({ family: font.family, status: font.status })));
      assert.ok(fonts.some(font => font.family === "Inter" && font.status === "loaded"));
      assert.ok(fonts.some(font => font.family === "Fraunces" && font.status === "loaded"));
      const inspectLayout = async () => {
        const issues = await page.evaluate(() => {
          const issues = [];
          if (document.documentElement.scrollWidth > innerWidth) issues.push("horizontal overflow");
          for (const el of document.querySelectorAll("h1, h2, h3, .service, .date-tab, .badge, .time-number, .barber")) {
            if (!el.getClientRects().length) continue;
            const rect = el.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect();
            if (rect.left < -1 || rect.right > innerWidth + 1) issues.push("outside viewport: " + el.className);
            if (el.scrollWidth > el.clientWidth + 1) issues.push("text overflow: " + el.className);
            if (rect.left < parent.left - 1 || rect.right > parent.right + 1) issues.push("outside parent: " + el.className);
          }
          const cards = [...document.querySelectorAll(".day-section:not([hidden]) .appointment")];
          for (let i = 1; i < cards.length; i++) {
            if (cards[i].getBoundingClientRect().top < cards[i - 1].getBoundingClientRect().bottom) issues.push("overlapping cards");
          }
          return issues;
        });
        assert.deepEqual(issues, [], width + "px layout");
      };
      await inspectLayout();
      await page.screenshot({ path: path.join(output, "agenda-" + width + ".png"), fullPage: true });
      // Verify the external Lucide symbol is painted, not just an empty SVG element.
      const icon = PNG.sync.read(await page.locator("#refresh .icon").screenshot());
      let painted = 0;
      for (let i = 0; i < icon.data.length; i += 4) {
        if (icon.data[i] < 100 && icon.data[i + 1] < 140 && icon.data[i + 2] < 120) painted++;
      }
      assert.ok(painted > 15, "Refresh icon must render");

      const tabs = page.getByRole("tab");
      for (let i = 0; i < 7; i++) {
        await tabs.nth(i).click();
        await page.waitForTimeout(180);
        assert.equal(await tabs.nth(i).getAttribute("aria-selected"), "true");
        assert.equal(await page.getByRole("tabpanel").count(), 1);
        await inspectLayout();
      }
      await tabs.nth(2).click();
      assert.match(await page.getByRole("tabpanel").innerText(), /Sin citas este/);
      if (width === 390) await page.screenshot({ path: path.join(output, "agenda-empty.png"), fullPage: true });
      await tabs.nth(1).click();
      await tabs.nth(1).press("End");
      assert.equal(await tabs.nth(6).getAttribute("aria-selected"), "true");
      await tabs.nth(6).press("Home");
      await tabs.nth(0).press("ArrowRight");
      assert.equal(await tabs.nth(1).getAttribute("aria-selected"), "true");
      const selectedUrl = page.url();
      await page.getByRole("button", { name: "Actualizar agenda" }).click();
      await page.waitForLoadState("load");
      assert.equal(page.url(), selectedUrl);
      assert.equal(await tabs.nth(1).getAttribute("aria-selected"), "true");
      await inspectLayout();
      if (width === 390) await page.screenshot({ path: path.join(output, "agenda-long-name.png"), fullPage: true });

      await page.goto(base + "/?scope=Obed");
      assert.match(await page.locator(".scope-label").innerText(), /Obed/);
      assert.ok((await page.locator(".barber").allTextContents()).every(name => name === "Obed"));
      await page.goto(base + "/?empty=true");
      assert.match(await page.locator(".week-heading").innerText(), /0 citas/);
      await inspectLayout();
      await page.goto(base + "/expired");
      assert.match(await page.locator("h1").innerText(), /no est/);
      await inspectLayout();
      await page.close();
      console.log("PASS " + width + "x" + height + ": assets, typography, layout, 7 days, keyboard, refresh, scope, empty, expired");
    }
    assert.deepEqual(errors, []);
    console.log("All visual checks passed. Screenshots: " + output);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
