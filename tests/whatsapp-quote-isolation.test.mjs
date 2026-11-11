import test from 'node:test';
import assert from 'node:assert/strict';
import {buildTextSendPayload,extractBridgeEvent} from '../whatsapp-bridge/bridge_helpers.js';

test('outbound quoting requires the same normalized chat',()=>{
 const quoted={key:{remoteJid:'111:2@s.whatsapp.net'},message:{conversation:'private'}};
 const messageStore=new Map([['q',quoted]]);
 assert.equal(buildTextSendPayload('reply',{chatId:'222@s.whatsapp.net',replyTo:'q',messageStore}).options.quoted,undefined);
 assert.equal(buildTextSendPayload('reply',{chatId:'111@s.whatsapp.net',replyTo:'q',messageStore}).options.quoted,quoted);
 assert.equal(buildTextSendPayload('reply',{replyTo:'q',messageStore}).options.quoted,undefined);
});

test('inbound metadata cannot request a different chat cache',async()=>{
 let calls=[];
 const args={msg:{key:{id:'m'},message:{extendedTextMessage:{text:'reply',contextInfo:{stanzaId:'q',remoteJid:'222@s.whatsapp.net'}}}},chatId:'111@s.whatsapp.net',senderId:'111@s.whatsapp.net',senderNumber:'111',lookupQuotedMedia:(...params)=>{calls.push(params);return {body:'private text'};}};
 await extractBridgeEvent(args);assert.deepEqual(calls,[]);
 delete args.msg.message.extendedTextMessage.contextInfo.remoteJid;
 await extractBridgeEvent(args);assert.deepEqual(calls,[['111@s.whatsapp.net','q']]);
});
