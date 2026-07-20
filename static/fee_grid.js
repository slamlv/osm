/* =========================================================================
   fee_grid.js — Grille tarifaire (static/js/fee_grid.js)
   Externe + différé + sans handler inline :
   - robuste au chargement defer de Bootstrap (instanciation paresseuse)
   - compatible CSP stricte (aucun script/onclick inline dans le template)
   ========================================================================= */
(function () {
  'use strict';

  let FEES = {};

  function modal() {
    // instanciation PARESSEUSE : bootstrap est forcément chargé au moment du clic
    return bootstrap.Modal.getOrCreateInstance(document.getElementById('feeModal'));
  }

  function addInstRow(label, amount, date) {
    const row = document.createElement('div');
    row.className = 'inst-row';
    row.innerHTML =
      '<input type="text" name="inst_label" class="form-control form-control-sm" placeholder="Libellé">' +
      '<input type="number" name="inst_amount" class="form-control form-control-sm inst-amt" placeholder="Montant" min="1">' +
      '<input type="date" name="inst_date" class="form-control form-control-sm">' +
      '<button type="button" class="btn btn-sm btn-outline-danger inst-del"><i class="bi bi-x"></i></button>';
    row.querySelector('[name=inst_label]').value = label || '';
    row.querySelector('[name=inst_amount]').value = amount || '';
    row.querySelector('[name=inst_date]').value = date || '';
    document.getElementById('inst-rows').appendChild(row);
  }

  function updateSum() {
    let s = 0;
    document.querySelectorAll('.inst-amt').forEach(i => s += (parseInt(i.value) || 0));
    const total = parseInt(document.getElementById('ff-amount').value) || 0;
    const el = document.getElementById('inst-sum');
    if (!document.querySelectorAll('.inst-amt').length) { el.textContent = ''; return; }
    el.textContent = 'Somme des tranches : ' + s + ' / ' + total;
    el.style.color = (s === total) ? '#5dd48e' : '#ff8a95';
  }

  function openFeeModal(feeId) {
    const typeSel = document.getElementById('ff-type');
    if (!typeSel || !typeSel.options.length) {
      alert("Aucun type de frais n'est défini pour cet établissement.\n" +
            "Créez-en un (section « Nouveau type de frais ») ou exécutez " +
            "l'initialisation des données par défaut.");
      return;
    }
    const f = feeId ? FEES[feeId] : null;
    document.getElementById('feeModalTitle').textContent =
      f ? 'Modifier la ligne de grille' : 'Nouvelle ligne de grille';
    document.getElementById('ff-id').value = feeId || '';
    typeSel.value = f ? f.fee_type : typeSel.options[0].value;
    document.getElementById('ff-level').value = f ? f.level : '';
    document.getElementById('ff-serie').value = f ? f.serie : '';
    document.getElementById('ff-amount').value = f ? f.amount : '';
    document.getElementById('inst-rows').innerHTML = '';
    if (f) f.installments.forEach(i => addInstRow(i.label, i.amount, i.due_date));
    updateSum();
    modal().show();
  }

  document.addEventListener('DOMContentLoaded', function () {
    // données des lignes (bloc JSON non exécutable -> CSP-safe)
    const dataEl = document.getElementById('fees-data');
    if (dataEl) { try { FEES = JSON.parse(dataEl.textContent); } catch (e) { FEES = {}; } }

    // délégation : AUCUN onclick/onsubmit inline dans le template
    document.addEventListener('click', function (ev) {
      const openBtn = ev.target.closest('[data-fee-open]');
      if (openBtn) { openFeeModal(openBtn.dataset.feeOpen || null); return; }
      if (ev.target.closest('.inst-del')) {
        ev.target.closest('.inst-row').remove(); updateSum(); return;
      }
      if (ev.target.closest('#inst-add')) { addInstRow(); return; }
    });

    document.addEventListener('input', function (ev) {
      if (ev.target.classList.contains('inst-amt') || ev.target.id === 'ff-amount') updateSum();
    });

    // confirmations (remplace les onsubmit inline)
    document.addEventListener('submit', function (ev) {
      const f = ev.target.closest('form[data-confirm]');
      if (f && !window.confirm(f.dataset.confirm)) ev.preventDefault();
    });
  });
})();
