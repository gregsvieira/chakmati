// The calendar on the panel: today's events.

(function () {
  const P = window.Panel;
  const { $, fill } = P;

  function renderAgenda() {
    const cal = (P.state.overview && P.state.overview.calendar) || { enabled: false };
    $('agenda').hidden = !cal.enabled;
    if (!cal.enabled) return;
    if (cal.error) { fill($('agenda-body'), P.h('p', { class: 'warn' }, 'Não consegui ler a agenda.')); return; }
    const events = cal.today || [];
    if (!events.length) { fill($('agenda-body'), P.h('p', { class: 'empty' }, 'Nada marcado para hoje.')); return; }
    const masked = P.state.settings.masked;
    fill($('agenda-body'), events.map((e) => {
      const time = e.all_day ? 'dia todo' : new Date(e.start).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      return P.h('div', { class: 'row' }, P.h('span', { class: 'name' }, masked ? 'Compromisso' : e.title), P.h('span', { class: 'time' }, time));
    }));
  }

  Object.assign(P, { renderAgenda });

})();
