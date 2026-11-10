#!/usr/bin/env python3
"""Narrow reviewed Baileys PR2765 backport; abort on an unexpected source."""
import hashlib
import json
from pathlib import Path
import shutil

SOURCE=Path(__file__).resolve().parent
LIB=Path('/opt/personal-agents/whatsapp-bridge/node_modules/@whiskeysockets/baileys/lib')
socket=LIB/'Socket/socket.js'
ack=LIB/'Socket/messages-recv.js'
marker='// Ji Eun compatibility backport: upstream Baileys PR2765'
if marker in socket.read_text():
    print('QR pairing compatibility fix already installed')
    raise SystemExit(0)
text=socket.read_text()
originals={str(p.relative_to(LIB)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [socket,ack]}
def change(old,new):
    global text
    if text.count(old)!=1:raise SystemExit('Unexpected Baileys source; compatibility patch not applied')
    text=text.replace(old,new,1)
change("import { Boom } from '@hapi/boom';", "import { Boom } from '@hapi/boom';\n"+marker+"\nimport { makePairingQRRenderer, handleCompanionRegRefresh } from '../Utils/ji-eun-pairing-compat.mjs';")
change('    // QR gen\n','    let refreshPairingQR;\n    // QR gen\n')
change('        const advB64 = creds.advSecretKey;', '''        const renderer = makePairingQRRenderer(
            refNodes.map(node => node.content.toString('utf-8')),
            ref => ev.emit('connection.update', { qr: buildPairingQRData(ref, noiseKeyB64, identityKeyB64, creds.advSecretKey, browser) })
        );
        refreshPairingQR = () => renderer.refresh();''')
change("            const refNode = refNodes.shift();\n            if (!refNode) {", "            if (!renderer.next()) {")
change("            const ref = refNode.content.toString('utf-8');\n            const qr = buildPairingQRData(ref, noiseKeyB64, identityKeyB64, advB64, browser);\n            ev.emit('connection.update', { qr });\n", '')
change('    // device paired for the first time', '''    ws.on('CB:notification,type:companion_reg_refresh', node => {
        handleCompanionRegRefresh(node, {
            creds,
            emitCredsUpdate: update => ev.emit('creds.update', update),
            refreshQR: () => refreshPairingQR?.(),
        });
    });
    // device paired for the first time''')
acktext=ack.read_text()
old='        const stanza = buildAckStanza(node, errorCode, authState.creds.me.id);'
new='''        const meId = authState.creds.me?.id;
        if (node.tag === 'message' && !meId) {
            throw new Boom('cannot ack a message before creds.me is set');
        }
        const stanza = buildAckStanza(node, errorCode, meId);'''
if acktext.count(old)!=1:raise SystemExit('Unexpected ACK source; nothing changed')
shutil.copy2(SOURCE/'whatsapp-pairing-compat.mjs',LIB/'Utils/ji-eun-pairing-compat.mjs')
socket.write_text(text);ack.write_text(acktext.replace(old,new,1))
(SOURCE/'whatsapp-pairing-compat-manifest.json').write_text(json.dumps({
    'source':'https://github.com/WhiskeySockets/Baileys/pull/2765',
    'upstream_head':'042fe1f3ddacf63ac2288837fbc8a395556bbb6e',
    'base_version':'7.0.0-rc13','original_sha256':originals,
    'patched_sha256':{str(p.relative_to(LIB)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [socket,ack]},
},indent=2)+'\n')
print('Applied isolated QR refresh and pre-login ACK compatibility fix')
