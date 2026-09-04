import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const compiled = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
function functionSource(name) {
  const start = compiled.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  return compiled.slice(start, compiled.indexOf('\n}', start) + 2);
}

test('runtime distinguishes configured, unavailable and expired without claiming live results', () => {
  const context = {};
  runInNewContext(functionSource('runtimeStatusLabel'), context);
  assert.match(context.runtimeStatusLabel({ provider_configured: false, source_registry_fresh: true }), /Modo seguro/);
  assert.match(context.runtimeStatusLabel({ provider_configured: true, source_registry_fresh: false }), /aguarda revisão/);
  const configured = context.runtimeStatusLabel({ provider_configured: true, source_registry_fresh: true });
  assert.match(configured, /configurada/);
  assert.doesNotMatch(configured, /ao vivo|consultada|conectada/);
});

test('every workspace button switches its view and exposes the selected area accessibly', () => {
  const names = ['chat', 'invoice', 'split', 'portfolio', 'governance'];
  const views = names.map((name) => ({ name, classList: new Set(['active']) }));
  views.forEach((view) => { view.classList.remove = view.classList.delete; });
  const buttons = names.map((name) => ({ dataset: { view: name }, classList: { toggle() {} }, setAttribute(key, value) { this[key] = value; } }));
  const title = {};
  const context = {
    innerWidth: 390, scrollTo() {}, VIEW_LABELS: Object.fromEntries(names.map((name) => [name, [name, name]])),
    selectElements: (selector) => selector === '.view' ? views : buttons,
    selectElement: (selector) => views.find((view) => selector === `#view-${view.name}`) ?? title,
  };
  runInNewContext(functionSource('switchView'), context);
  for (const name of names) {
    context.switchView(name);
    assert.deepEqual(views.filter((view) => view.classList.has('active')).map((view) => view.name), [name]);
    assert.equal(buttons.find((button) => button.dataset.view === name)['aria-current'], 'page');
  }
});
