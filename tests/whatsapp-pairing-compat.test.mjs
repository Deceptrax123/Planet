import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makePairingQRRenderer, handleCompanionRegRefresh } from '../whatsapp-pairing-compat.mjs';

const notification = tag => ({ content: tag ? [{tag}] : [] });
for (const tag of ['companion_reg_refresh','pair-device-rotate-qr']) {
  test(`refresh ${tag} rotates advertised secret without consuming a QR reference`, () => {
    const creds={advSecretKey:'old'};
    const rendered=[];const updates=[];
    const renderer=makePairingQRRenderer(['ref-1','ref-2'],ref => rendered.push([ref,creds.advSecretKey]));
    renderer.next();
    for (let n=0;n<50;n++) {
      assert.equal(handleCompanionRegRefresh(notification(tag),{
        creds,emitCredsUpdate:update=>updates.push(update),refreshQR:()=>renderer.refresh(),
      }),'rotated');
    }
    assert.equal(new Set(updates.map(x=>x.advSecretKey)).size,50);
    assert.equal(Buffer.from(creds.advSecretKey,'base64').length,32);
    assert.equal(rendered.at(-1)[0],'ref-1');
    assert.notEqual(rendered[0][1],rendered.at(-1)[1]);
    assert.equal(renderer.next(),true);
    assert.equal(rendered.at(-1)[0],'ref-2');
    assert.equal(renderer.next(),false);
  });
}
test('registered identity and malformed refresh never change keys', () => {
  for (const [creds,node] of [[{me:{id:'test'},advSecretKey:'existing'},notification('companion_reg_refresh')],[{advSecretKey:'existing'},notification()]]) {
    let actions=0;
    handleCompanionRegRefresh(node,{creds,emitCredsUpdate:()=>actions++,refreshQR:()=>actions++});
    assert.equal(creds.advSecretKey,'existing');assert.equal(actions,0);
  }
});
test('no QR can be refreshed before a reference has been displayed', () => {
  const renderer=makePairingQRRenderer(['one'],()=>assert.fail('must not render'));
  assert.equal(renderer.refresh(),false);
});
