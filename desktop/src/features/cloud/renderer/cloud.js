// The paid-AI section in Ajustes: what is connected, and a modal to connect, change the key or the model, or remove it. The key is typed here, sent once
// to the main process (which checks it with the provider and stores it encrypted) and cleared from the field at once; this page never sees it again.

(function () {
  const P = window.Panel;
  const { $, api } = P;
  let providers = [];

  const settings = () => (P.state && P.state.settings) || {};
  const connected = () => !!settings().cloudProvider;
  const nameOf = (id) => (providers.find((p) => p.id === id) || { label: id }).label;
  const showError = (text) => { $('cloud-error').textContent = text || ''; $('cloud-error').hidden = !text; };

  function renderCloud() {
    const s = settings();
    const on = connected();
    $('cloud-status').textContent = on
      ? `Conectada: ${nameOf(s.cloudProvider)} (${s.cloudModel}). ${s.localModel ? 'Quando o limite acabar, o modelo local responde.' : 'Sem modelo local de reserva.'}`
      : 'Nenhuma. O Chakmati usa só o modelo local.';
    $('cloud-open').textContent = on ? 'Trocar a chave ou o modelo' : 'Conectar a minha IA paga';
    $('cloud-remove').hidden = !on;
  }

  async function open() {
    if (!providers.length) providers = await api.cloudProviders();
    const s = settings();
    const pick = $('cloud-provider');
    pick.replaceChildren(...providers.map((p) => Object.assign(document.createElement('option'), { value: p.id, textContent: p.label })));
    pick.value = connected() ? s.cloudProvider : providers[0].id;
    const sync = () => {
      const p = providers.find((x) => x.id === pick.value);
      $('cloud-model').value = connected() && s.cloudProvider === pick.value ? s.cloudModel : p.defaultModel;
      $('cloud-help').textContent = connected() && s.cloudProvider === pick.value ? 'Deixe a chave em branco para manter a atual.' : `Crie a chave em ${p.keyHelp}.`;
    };
    pick.onchange = sync;
    sync();
    $('cloud-key').value = '';
    $('cloud-local').checked = connected() ? !!s.localModel : true;
    showError('');
    $('cloud-modal').hidden = false;
    $('cloud-key').focus();
  }

  function close() {
    $('cloud-key').value = '';
    $('cloud-modal').hidden = true;
    showError('');
  }

  async function save() {
    const key = $('cloud-key').value;
    $('cloud-key').value = '';   // gone from the page the moment it is sent
    $('cloud-save').disabled = true;
    $('cloud-save').textContent = 'Conferindo com o provedor…';
    const res = await api.cloudSave($('cloud-provider').value, key, $('cloud-model').value.trim(), $('cloud-local').checked);
    $('cloud-save').disabled = false;
    $('cloud-save').textContent = 'Salvar';
    if (res.error) return showError(res.error);
    close();
    return renderCloud();
  }

  async function remove() {
    if (!window.confirm('Remover a sua IA paga? A chave é apagada deste computador e o Chakmati passa a usar só o modelo local (se ele não estiver instalado, o Chakmati não vai responder).')) return;
    await api.cloudRemove();
    renderCloud();
  }

  $('cloud-open').addEventListener('click', open);
  $('cloud-remove').addEventListener('click', remove);
  $('cloud-save').addEventListener('click', save);
  $('cloud-cancel').addEventListener('click', close);
  $('cloud-key').addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
  $('cloud-modal').addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  api.cloudProviders().then((list) => { providers = list; renderCloud(); });
  Object.assign(P, { renderCloud });
})();
