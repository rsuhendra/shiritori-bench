// Optional smoke test; uses an existing Playwright install and installed Chrome.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true,chromiumSandbox:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.argv[2] || 'http://127.0.0.1:8856/');
  await page.waitForFunction(()=>document.querySelector('#model-rows')?.innerText.includes('DeepSeek'));
  assert.equal(await page.locator('#load-error').isVisible(),false);
  assert.equal(await page.locator('[aria-label="Pilot dataset summary"]').count(),0);
  assert.equal(await page.locator('#model-rows tr').count(),2);
  assert.match(await page.locator('#competition-title').innerText(),/MemoryBot/);
  await page.getByRole('button',{name:'Model vs model',exact:true}).click();
  assert.match(await page.locator('#competition-note').innerText(),/2 same-configuration/);
  assert.match(await page.locator('#model-rows').innerText(),/self-play seats excluded/);
  await page.getByRole('button',{name:'Model vs MemoryBot',exact:true}).click();
  await page.locator('#tab-games').click();
  assert.equal(await page.locator('.game-option').count(),4);
  await page.locator('.game-option').filter({hasText:'Referee-policy warning'}).click();
  assert.match(await page.locator('#match-result').innerText(),/Historical referee artifact/);
  assert.match(await page.locator('#move-list').innerText(),/Not scored/);
  await page.locator('.move-strength summary').first().click();
  assert.match(await page.locator('.move-strength[open]').innerText(),/alternatives scored/);
  await page.locator('#tab-failures').click();
  assert.match(await page.locator('#failure-examples').innerText(),/まくら/);
  await page.locator('#tab-atlas').click();
  assert.ok(await page.locator('.kana-tile').count()>0);
  await page.locator('#tab-method').click();
  assert.match(await page.locator('#scoring-provenance').innerText(),/two-ply-log-mass-v1/);
  await page.locator('#tab-pilot').click();
  await page.locator('.evaluation-context').evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));
  await page.screenshot({path:'/tmp/shiritori-results-desktop.png',fullPage:false});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),true);
  await page.locator('.evaluation-context').evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));
  await page.screenshot({path:'/tmp/shiritori-results-mobile.png',fullPage:false});
  assert.deepEqual(errors,[]);
  console.log('Browser checks passed: competition filters, replay scores, historical warning, analysis, methodology, mobile layout; no JavaScript errors.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
