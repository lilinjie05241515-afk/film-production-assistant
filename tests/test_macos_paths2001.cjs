// Compare actual shipped board path identities; all paths are synthetic.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const context={module:{exports:{}},console};
new vm.Script(html.split('<script>')[1].split('</script>')[0]).runInNewContext(context);
const identity=context.module.exports.rootIdentity;
test('case-sensitive Mac project directories retain distinct identity',()=>{
  assert.notEqual(identity('/Volumes/TEST/Film'),identity('/Volumes/TEST/film'));
  assert.equal(identity('/Volumes/TEST/中文 空格/'),identity('/Volumes/TEST/中文 空格'));
});
test('Windows drive and UNC paths retain case-insensitive identity',()=>{
  assert.equal(identity('C:\\TEST\\Film\\'),identity('c:/test/film'));
  assert.equal(identity('\\\\TEST-SERVER\\Share\\Film'),identity('//test-server/share/film'));
});
