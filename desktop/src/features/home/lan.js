'use strict';
// The only addresses the connect flow may open or talk to: the person's own network. (The engine checks the same; this is the second lock.)
const net = require('node:net');

function privateV4(host) {
  const [a, b] = host.split('.').map(Number);
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
}

function isLocalHttpUrl(value) {
  let u;
  try { u = new URL(String(value)); } catch { return false; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
  if (u.username || u.password) return false;
  const host = u.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (net.isIPv4(host)) return privateV4(host);
  if (net.isIPv6(host)) return host === '::1' || host.startsWith('fe80:') || host.startsWith('fc') || host.startsWith('fd');
  return host === 'localhost' || host.endsWith('.local') || !host.includes('.');
}

module.exports = { isLocalHttpUrl };
