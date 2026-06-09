// client_multi_image_upload.js
(() => {
  // CONFIG
  const MAX_WIDTH = 1200;            // largeur max en px
  const QUALITY = 0.75;              // 0.0 -> 1.0 (réduit légèrement pour gagner du débit)
  const OUTPUT_TYPE = 'image/webp';  // 'image/webp' ou 'image/jpeg'
  const FILE_INPUT_CLASS = 'client-image';
  const FORM_CLASS = 'client-image-form';

  // Utilitaires
  function getCookie(name) {
    const v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return v ? v.pop() : '';
  }

  function createProgressElements(form) {
    if (form._clientProgress) return form._clientProgress;
    const container = document.createElement('div');
    container.className = 'client-upload-progress';
    container.style = 'margin-top:8px;';

    const barwrap = document.createElement('div');
    barwrap.style = 'width:100%; background:#eee; height:10px; border-radius:6px; overflow:hidden;';
    const bar = document.createElement('div');
    bar.className = 'bg-warning';
    bar.style = 'height:10px; width:0%';
    barwrap.appendChild(bar);

    const text = document.createElement('div');
    text.className = 'text-white';
    text.style = 'font-size:12px; margin-top:4px;';

    container.appendChild(barwrap);
    container.appendChild(text);
    form.appendChild(container);

    const obj = { container, bar, text };
    form._clientProgress = obj;
    return obj;
  }

  // resize + convert to Blob using canvas
  async function resizeAndConvert(file) {
    let imgBitmap;
    try {
      if (window.createImageBitmap) {
        imgBitmap = await createImageBitmap(file);
      } else {
        imgBitmap = await new Promise((res, rej) => {
          const i = new Image();
          i.onload = () => res(i);
          i.onerror = rej;
          i.src = URL.createObjectURL(file);
        });
      }
    } catch (err) {
      imgBitmap = await new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => res(i);
        i.onerror = rej;
        i.src = URL.createObjectURL(file);
      });
    }

    const naturalWidth = imgBitmap.width || imgBitmap.naturalWidth;
    const naturalHeight = imgBitmap.height || imgBitmap.naturalHeight;

    let targetWidth = naturalWidth;
    let targetHeight = naturalHeight;
    if (MAX_WIDTH && naturalWidth > MAX_WIDTH) {
      targetWidth = MAX_WIDTH;
      targetHeight = Math.round(naturalHeight * (MAX_WIDTH / naturalWidth));
    }

    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');

    try {
      ctx.drawImage(imgBitmap, 0, 0, targetWidth, targetHeight);
    } catch (err) {
      const tmpUrl = URL.createObjectURL(file);
      await new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => {
          ctx.drawImage(i, 0, 0, targetWidth, targetHeight);
          URL.revokeObjectURL(tmpUrl);
          res();
        };
        i.onerror = (e) => {
          URL.revokeObjectURL(tmpUrl);
          rej(e);
        };
        i.src = tmpUrl;
      });
    } finally {
      try { if (imgBitmap && imgBitmap.close) imgBitmap.close(); } catch (e) { /* ignore */ }
    }

    const mime = OUTPUT_TYPE;
    const quality = QUALITY;

    return await new Promise((resolve) => {
      canvas.toBlob((blob) => {
        if (!blob && mime === 'image/webp') {
          canvas.toBlob((b2) => resolve(b2), 'image/jpeg', quality);
        } else {
          resolve(blob);
        }
      }, mime, quality);
    });
  }

  window.OSMCompressImage = resizeAndConvert;

  // helper: create a File from a Blob (with filename & type)
  function blobToFile(blob, filename) {
    try {
      return new File([blob], filename, { type: blob.type });
    } catch (e) {
      // Older browsers: fallback to Blob with name property shim (may not set input.files properly)
      blob.name = filename;
      return blob;
    }
  }

  // navigateAndRender kept for AJAX path fallback (no X-Requested-With in fetch)
  async function navigateAndRender(url) {
    try {
      const resp = await fetch(url, { credentials: 'same-origin', method: 'GET' });
      if (!resp.ok) {
        window.location.assign(url);
        return;
      }
      const ct = resp.headers.get('Content-Type') || '';
      if (!ct.includes('text/html')) {
        window.location.assign(url);
        return;
      }
      const html = await resp.text();
      try {
        history.replaceState(null, '', url);
        document.open();
        document.write(html);
        document.close();
      } catch (err) {
        window.location.assign(url);
      }
    } catch (err) {
      window.location.assign(url);
    }
  }

  // Trouve la checkbox Django "clear" associée à un file input.
  // Django génère : id="<field>-clear_id" name="<field>-clear"
  function getClearCheckbox(input) {
    const id = input.id;
    const name = input.name;
    return (
      (id   && document.querySelector(`input[type="checkbox"][id="${id}-clear_id"]`))   ||
      (name && document.querySelector(`input[type="checkbox"][name="${name}-clear"]`))  ||
      null
    );
  }

  // Init
  function init() {
    const forms = document.querySelectorAll(`form.${FORM_CLASS}`);
    forms.forEach(form => setupForm(form));
  }

  function setupForm(form) {
    // Map input element -> Array of compressed info (for potential multiple files later)
    // For single-file inputs we store an array length 1.
    const compressedMap = new Map();

    const fileInputs = Array.from(form.querySelectorAll(`input[type=file].${FILE_INPUT_CLASS}`));

    fileInputs.forEach(input => {
      const preview = document.createElement('img');
      preview.style = 'max-width:200px; margin-top:6px; border:1px solid #ddd; padding:4px; border-radius:4px;';
      preview.style.display = 'none';
      input.insertAdjacentElement('afterend', preview);

      // --- Aperçu de l'image existante (déjà enregistrée, ex. Cloudinary) ---
      // On cherche un data-current-url sur l'input, sinon on remonte au widget Django
      // qui affiche un <a> ou <img> avec l'URL courante.
      const currentUrl = input.dataset.currentUrl || (() => {
        // Django ClearableFileInput rend un lien "Actuellement : <a href="...">..."
        // juste avant le widget ; on le cherche dans le parent proche.
        const parent = input.closest('.mb-3, .form-group, p, div') || input.parentElement;
        const link = parent && parent.querySelector('a[href]');
        if (link) {
          const href = link.getAttribute('href');
          if (/\.(jpg|jpeg|png|gif|webp|svg)(\?|$)/i.test(href) || href.includes('cloudinary')) return href;
        }
        return null;
      })();

      if (currentUrl) {
        preview.src = currentUrl;
        preview.style.display = '';
      }

      let info = null;

      // --- Checkbox Django "Effacer" ---
      const clearCb = getClearCheckbox(input);
      if (clearCb) {
        clearCb.addEventListener('change', function () {
          if (clearCb.checked) {
            // L'utilisateur veut supprimer l'image : vide la sélection et masque l'aperçu
            input.value = '';
            compressedMap.delete(input);
            if (preview._url) { try { URL.revokeObjectURL(preview._url); } catch (e) {} preview._url = null; }
            preview.src = '';
            preview.style.display = 'none';
            if (info) info.textContent = '';
          }
        });
      }

      input.addEventListener('change', async (e) => {
        // support only first file (keeps parity with your original)
        const f = e.target.files && e.target.files[0];
        if (preview._url) { try { URL.revokeObjectURL(preview._url); } catch (err) {} preview._url = null; }
        if (info && info._url) { try { URL.revokeObjectURL(info._url); } catch (err) {} info._url = null; }

        if (!f) {
          compressedMap.delete(input);
          // Si pas de nouveau fichier, réafficher l'image existante si elle existe
          if (currentUrl) {
            preview.src = currentUrl;
            preview.style.display = '';
          } else {
            preview.style.display = 'none';
          }
          if (info) info.textContent = '';
          return;
        }

        // Un nouveau fichier est sélectionné : décocher la checkbox "clear" si présente
        if (clearCb) clearCb.checked = false;

        preview._url = URL.createObjectURL(f);
        preview.src = preview._url;
        preview.style.display = '';

        try {
          const blob = await resizeAndConvert(f);
          if (!blob) throw new Error('Conversion returned empty blob');

          const originalName = f.name || 'photo';
          const base = originalName.includes('.') ? originalName.substring(0, originalName.lastIndexOf('.')) : originalName;
          const ext = blob.type === 'image/webp' ? 'webp' : (blob.type === 'image/jpeg' ? 'jpg' : 'img');
          const filename = base + '.' + ext;

          // store one-element array to keep extensibility
          compressedMap.set(input, [{
            blob,
            filename,
            originalSize: f.size,
            compressedSize: blob.size
          }]);

          if (preview._url) { try { URL.revokeObjectURL(preview._url); } catch (err) {} preview._url = null; }
          preview._url = URL.createObjectURL(blob);
          preview.src = preview._url;

          if (!info) {
            info = document.createElement('div');
            info.className = 'text-white';
            info.style = 'font-size:12px; margin-top:4px; color:inherit';
            input.insertAdjacentElement('afterend', info);
          }
          info.textContent = `Prêt : ${ (f.size/1024).toFixed(1) }KB → ${ (blob.size/1024).toFixed(1) }KB`;

        } catch (err) {
          console.error('Erreur traitement image:', err);
          compressedMap.delete(input);
          preview.style.display = 'none';
          if (!info) {
            info = document.createElement('div');
            info.className = 'text-white';
            info.style = 'font-size:12px; margin-top:4px; color:inherit';
            input.insertAdjacentElement('afterend', info);
          }
          info.textContent = 'Erreur lors du traitement côté client';
        }
      });
    });

    // Submit handler
    form.addEventListener('submit', async (ev) => {
      // If no special file inputs, nothing to do
      if (fileInputs.length === 0) return;

      // Decide method: native submit (default) vs AJAX upload
      // If form has data-ajax="1" we use XHR (old behaviour). Otherwise native submit to preserve Django messages.
      const useAjax = form.getAttribute('data-ajax') === '1';

      if (!useAjax) {
        // Native submit path: replace file inputs' .files with File(s) created from blobs, then call native submit.
        ev.preventDefault();

        // Prepare UI (indeterminate progress)
        const prog = createProgressElements(form);
        prog.bar.style.width = '100%';
        prog.text.textContent = 'Envoi en cours...';
        prog.text.className = 'text-white';
        prog.container.style.display = '';

        // For each file input, if we have compressed blob(s), create a DataTransfer and assign new files.
        try {
          fileInputs.forEach(input => {
            const arr = compressedMap.get(input);
            if (!arr || arr.length === 0) return;
            // build DataTransfer with new File(s)
            const dt = new DataTransfer();
            arr.forEach(info => {
              const fileObj = blobToFile(info.blob, info.filename);
              dt.items.add(fileObj);
            });
            // assign files to input
            try {
              input.files = dt.files;
            } catch (e) {
              // Some browsers may not allow setting input.files; fallback below by creating a temporary form
              console.warn('Impossible de définir input.files sur ce navigateur, fallback activé.');
              throw new Error('cannot-set-input-files');
            }
          });

          // temporarily remove this submit listener to avoid loop when calling form.submit()
          form.removeEventListener('submit', arguments.callee);

          // submit form normally (browser will perform navigation -> Django messages will show)
          form.submit();
        } catch (err) {
          // Fallback: if we cannot set input.files (older browsers), create a hidden form and append File objects via fetch/XHR
          // We'll fallback to AJAX upload using XHR so at least upload proceeds — after that we'll navigate to server response.
          console.warn('Fallback to AJAX upload because input.files could not be set:', err);

          // Build FormData from form
          const fd = new FormData(form);
          // Replace file entries using compressedMap where possible
          fileInputs.forEach(input => {
            const name = input.name;
            if (!name) return;
            const arr = compressedMap.get(input);
            if (arr && arr.length) {
              fd.delete(name);
              arr.forEach(info => fd.append(name, info.blob, info.filename));
            }
          });

          // send via XHR without X-Requested-With header (we removed it previously)
          const xhr = new XMLHttpRequest();
          const action = form.getAttribute('action') || window.location.href;
          const method = (form.getAttribute('method') || 'POST').toUpperCase();
          xhr.open(method, action, true);

          // CSRF
          const csrftoken = getCookie('csrftoken') || form.querySelector('[name=csrfmiddlewaretoken]')?.value;
          if (csrftoken) xhr.setRequestHeader('X-CSRFToken', csrftoken);

          // disable controls
          const controls = Array.from(form.querySelectorAll('input,button,textarea,select'));
          controls.forEach(c => c.disabled = true);

          xhr.onload = async () => {
            controls.forEach(c => c.disabled = false);

            // Try parse JSON redirect first
            try {
              const data = JSON.parse(xhr.responseText || '{}');
              if (data && data.redirect) {
                await navigateAndRender(data.redirect);
                return;
              }
            } catch (e) { /* not JSON */ }

            // If 3xx with Location
            if (xhr.status >= 300 && xhr.status < 400) {
              const loc = xhr.getResponseHeader('Location');
              if (loc) {
                await navigateAndRender(loc);
                return;
              }
            }

            // If responseURL different
            if (xhr.responseURL) {
              const initial = (action || window.location.href).split('#')[0];
              const final = xhr.responseURL.split('#')[0];
              if (final && final !== initial) {
                await navigateAndRender(final);
                return;
              }
            }

            // fallback: if status 2xx but no redirect info, reload page
            if (xhr.status >= 200 && xhr.status < 300) {
              window.location.reload();
            } else {
              alert('Erreur upload (' + xhr.status + ')');
            }
          };

          xhr.onerror = () => {
            controls.forEach(c => c.disabled = false);
            alert('Erreur réseau pendant l\'upload.');
          };

          xhr.send(fd);
        }
        return;
      }

      // ---------- AJAX path (only when data-ajax="1") ----------
      ev.preventDefault();
      const fd = new FormData(form);
      fileInputs.forEach(input => {
        const name = input.name;
        if (!name) return;
        const entryArr = compressedMap.get(input);
        if (entryArr && entryArr.length) {
          fd.delete(name);
          entryArr.forEach(entry => fd.append(name, entry.blob, entry.filename));
        }
      });

      const prog = createProgressElements(form);
      prog.bar.style.width = '0%';
      prog.text.textContent = '';
      prog.text.className = 'text-white';
      prog.container.style.display = '';

      const xhr = new XMLHttpRequest();
      const action = form.getAttribute('action') || window.location.href;
      const method = (form.getAttribute('method') || 'POST').toUpperCase();
      xhr.open(method, action, true);

      // CSRF
      const csrftoken = getCookie('csrftoken') || form.querySelector('[name=csrfmiddlewaretoken]')?.value;
      if (csrftoken) xhr.setRequestHeader('X-CSRFToken', csrftoken);
      // NOTE: we do NOT set X-Requested-With to force server to act as normal where possible

      const controls = Array.from(form.querySelectorAll('input,button,textarea,select'));
      controls.forEach(c => c.disabled = true);

      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          const pct = Math.round((ev.loaded / ev.total) * 100);
          prog.bar.style.width = pct + '%';
          prog.text.textContent = `${pct}%`;
          prog.text.className = 'text-white';
        } else {
          prog.text.textContent = 'Envoi...';
          prog.text.className = 'text-white';
        }
      };

      xhr.onload = async () => {
        controls.forEach(c => c.disabled = false);

        // Try JSON redirect
        try {
          const data = JSON.parse(xhr.responseText || '{}');
          if (data && data.redirect) {
            await navigateAndRender(data.redirect);
            return;
          }
        } catch (e) { /* not JSON */ }

        if (xhr.status >= 300 && xhr.status < 400) {
          const loc = xhr.getResponseHeader('Location');
          if (loc) {
            await navigateAndRender(loc);
            return;
          }
        }

        if (xhr.responseURL) {
          const initial = (action || window.location.href).split('#')[0];
          const final = xhr.responseURL.split('#')[0];
          if (final && final !== initial) {
            await navigateAndRender(final);
            return;
          }
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          prog.bar.style.width = '100%';
          prog.text.textContent = '100% - Téléversement terminé';
          prog.text.className = 'text-white';
          const targetSel = form.getAttribute('data-success-target');
          if (targetSel) {
            const tgt = document.querySelector(targetSel);
            if (tgt) {
              tgt.textContent = 'Téléversement réussi.';
              tgt.classList && tgt.classList.add('text-white');
            }
          } else {
            alert('Téléversement réussi.');
          }
        } else {
          prog.text.textContent = `Erreur upload (${xhr.status})`;
          prog.text.className = 'text-white';
          alert(`Erreur upload (${xhr.status})`);
        }
      };

      xhr.onerror = () => {
        controls.forEach(c => c.disabled = false);
        prog.text.textContent = 'Erreur réseau pendant l\'upload.';
        prog.text.className = 'text-white';
        alert('Erreur réseau pendant l\'upload.');
      };

      xhr.send(fd);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
