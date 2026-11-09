// The "+" of the conversation: attach files, and ask about them or ask for a summary. The files stay attached to the conversation (the chips above the
// field) until the person removes them, so follow-up questions work. Only the engine reads them; this window just hands the bytes over.
(function () {
  const P = window.Panel;
  const { $, api, h } = P;
  const L = window.AttachLogic;
  const attached = [];   // { id, name } of the files the conversation is about

  const note = (text) => { const n = $('attached-note'); n.textContent = text || ''; n.hidden = !text; };

  function renderChips(pending = []) {
    const box = $('attached');
    box.hidden = !attached.length && !pending.length;
    box.replaceChildren(
      h('span', { class: 'attached-label' }, 'Falando sobre:'),
      ...attached.map((f) => h('span', { class: 'chip-file', title: f.name },
        h('span', { class: 'chip-name' }, L.shortName(f.name)),
        h('button', { type: 'button', class: 'chip-x', 'aria-label': `Remover ${f.name}`, title: 'Remover', onclick: () => remove(f.id) }, '×'))),
      ...pending.map((name) => h('span', { class: 'chip-file pending', title: name }, h('span', { class: 'chip-name' }, `Lendo ${L.shortName(name, 20)}…`))));
    $('attach').setAttribute('aria-label', attached.length ? `Anexar mais arquivos (${attached.length} anexado${attached.length > 1 ? 's' : ''})` : 'Anexar arquivo');
    P.input.placeholder = attached.length ? 'Pergunte algo ou peça um resumo do arquivo…' : 'Peça algo ao Chakmati…';
  }

  async function remove(id) {
    const i = attached.findIndex((f) => f.id === id);
    if (i >= 0) attached.splice(i, 1);
    renderChips();
    try { await api.detach(id); } catch { /* the engine sweeps old files by itself */ }
  }

  async function add(files) {
    note('');
    const pending = [];
    for (const file of files) {
      const problem = L.check(file, attached.length + pending.length);
      if (problem) { note(`${file.name}: ${problem}`); continue; }
      pending.push(file.name);
      renderChips(pending);
      const res = await api.attach(file.name, new Uint8Array(await file.arrayBuffer()));
      pending.splice(pending.indexOf(file.name), 1);
      if (res && res.id) attached.push({ id: res.id, name: res.name || file.name });
      else note(`${file.name}: ${(res && res.error) || 'não consegui ler o arquivo.'}`);
      renderChips(pending);
    }
    renderChips();
  }

  P.inits.push(function () {
    const input = $('attach-input');
    input.accept = L.ACCEPT;
    $('attach').addEventListener('click', () => { if (!(P.state && P.state.busy)) input.click(); });
    input.addEventListener('change', () => { const chosen = [...input.files]; input.value = ''; add(chosen); });
  });

  Object.assign(P, { attachedIds: () => attached.map((f) => f.id), attachedCount: () => attached.length });
})();
