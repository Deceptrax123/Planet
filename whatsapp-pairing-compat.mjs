// Minimal JS backport of WhiskeySockets/Baileys PR #2765 at
// 042fe1f3ddacf63ac2288837fbc8a395556bbb6e. This lives only in our
// isolated bridge dependency, not the pinned Hermes vendor checkout.
import { randomBytes } from 'node:crypto';

export function makePairingQRRenderer(refs, render) {
  let index = 0;
  let current;
  return {
    next() {
      const ref = refs[index];
      if (ref === undefined) return false;
      index += 1;
      current = ref;
      render(ref);
      return true;
    },
    refresh() {
      if (current === undefined) return false;
      render(current);
      return true;
    },
  };
}

export function handleCompanionRegRefresh(node, { creds, emitCredsUpdate, refreshQR }) {
  const validChild = Array.isArray(node.content) && node.content.some(
    child => ['companion_reg_refresh', 'pair-device-rotate-qr'].includes(child?.tag));
  if (!validChild) return 'ignored_malformed';
  if (creds.me) return 'ignored_registered';
  creds.advSecretKey = randomBytes(32).toString('base64');
  emitCredsUpdate({ advSecretKey: creds.advSecretKey });
  refreshQR();
  return 'rotated';
}
