'use strict';
// Connecting the paid AI, one place for both doors (the install wizard and Ajustes): validate what was typed, check the key with the provider,
// and only a key the provider accepted is stored (encrypted). -> { ok } | { error }
const { validProvider, validModel, validKey, checkKey } = require('./cloud-key');

function createCloudSetup({ keyStore, check = checkKey }) {
  return {
    async connect(provider, key, model) {
      if (!validProvider(provider)) return { error: 'Escolha o provedor.' };
      if (!validModel(model)) return { error: 'O nome do modelo tem caracteres inválidos.' };
      if (!validKey(key)) return { error: 'A chave tem um formato inválido (sem espaços nem quebras de linha).' };
      if (!keyStore.available()) return { error: 'Este computador não tem um cofre do sistema para guardar a chave com segurança, então não vou guardá-la.' };
      const checked = await check(provider, key);
      if (checked.error) return checked;
      try { keyStore.save(key); } catch (e) { return { error: e.message }; }
      return { ok: true };
    },
  };
}

module.exports = { createCloudSetup };
