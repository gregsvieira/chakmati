'use strict';
// Which files the "+" of the conversation accepts, and the sentence for the ones it does not. Pure (the window and the main process share it).
(function (root) {
  const MAX_FILES = 5;
  const MAX_BYTES = 20 * 1024 * 1024;
  const TEXT = ['.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.log', '.xml', '.html', '.htm', '.yaml', '.yml', '.ini', '.srt', '.py', '.js', '.ts', '.sql'];
  const OFFICE = ['.pdf', '.docx', '.xlsx', '.pptx'];
  const ACCEPT = [...TEXT, ...OFFICE].join(',');

  const extension = (name) => { const m = /\.[^./\\]+$/.exec(String(name || '')); return m ? m[0].toLowerCase() : ''; };

  // null when the file can be attached; else what to tell the person
  function check(file, alreadyAttached) {
    if (alreadyAttached >= MAX_FILES) return `Dá para anexar até ${MAX_FILES} arquivos por conversa.`;
    if (!file || !file.name) return 'Arquivo inválido.';
    if (!ACCEPT.split(',').includes(extension(file.name))) return 'Esse tipo de arquivo ainda não é lido. Use texto, PDF, Word, Excel ou PowerPoint.';
    if (!(file.size > 0)) return 'O arquivo está vazio.';
    if (file.size > MAX_BYTES) return 'O arquivo é grande demais (o limite é 20 MB).';
    return null;
  }

  // a long name shortened in the middle, keeping the extension, so the chip stays small
  function shortName(name, max = 26) {
    const text = String(name || '');
    if (text.length <= max) return text;
    const ext = extension(text);
    const keep = Math.max(4, max - ext.length - 1);
    return `${text.slice(0, keep)}…${ext}`;
  }

  const api = { MAX_FILES, MAX_BYTES, ACCEPT, extension, check, shortName };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AttachLogic = api;
})(typeof window !== 'undefined' ? window : globalThis);
