const assert=require('node:assert/strict');const {test}=require('node:test');const fs=require('node:fs');const {esc}=require('../web/app.js');
test('legacy display escapes content without executing markup',()=>{assert.equal(esc('<script>"&'), '&lt;script&gt;&quot;&amp;');});
test('legacy UI has only GET reads and no business entry points',()=>{const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');assert.match(source,/method:"GET"/);assert.doesNotMatch(source,/\/api\/dispatch|task\.(create|submit|checkpoint)|artifact\.save|ui\/message/);});
