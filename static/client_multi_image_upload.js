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
    // if already created, return
    if (form._clientProgress) return form._clientProgress;
    const container = document.createElement('div');
    container.className = 'client-upload-progress';
    container.style = 'margin-top:8px;';

    const barwrap = document.createElement('div');
    barwrap.style = 'width:100%; background:#eee; height:10px; border-radius:6px; overflow:hidden;';
    const bar = document.createElement('div');
    // apply bootstrap-ish class for bg-warning while keeping inline width control
    bar.className = 'bg-warning';
    bar.style = 'height:10px; width:0%';
    barwrap.appendChild(bar);

    const text = document.createElement('div');
    // make progress text white
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
    // Use createImageBitmap when available (faster decoding, non-blocking)
    let imgBitmap;
    try {
      if (window.createImageBitmap) {
        imgBitmap = await createImageBitmap(file);
      } else {
        // fallback to Image()
        imgBitmap = await new Promise((res, rej) => {
          const i = new Image();
          i.onload = () => res(i);
          i.onerror = rej;
          i.src = URL.createObjectURL(file);
        });
      }
    } catch (err) {
      // fallback to Image() if createImageBitmap fails
      imgBitmap = await new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => res(i);
        i.onerror = rej;
        i.src = URL.createObjectURL(file);
      });
    }

    const naturalWidth = imgBitmap.width || imgBitmap.naturalWidth;
    const naturalHeight = imgBitmap.height || imgBitmap.naturalHeight;

    // compute new size
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

    // draw using bitmap or image element
    try {
      ctx.drawImage(imgBitmap, 0, 0, targetWidth, targetHeight);
    } catch (err) {
      // If drawing a bitmap fails, try creating an Image from blob URL
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
      // try to close bitmap if supported
      try { if (imgBitmap && imgBitmap.close) imgBitmap.close(); } catch (e) { /* ignore */ }
    }

    const mime = OUTPUT_TYPE;
    const quality = QUALITY;

    // wrapper promise for toBlob with webp fallback
    return await new Promise((resolve) => {
      canvas.toBlob((blob) => {
        if (!blob && mime === 'image/webp') {
          // fallback to jpeg
          canvas.toBlob((b2) => resolve(b2), 'image/jpeg', quality);
        } else {
          resolve(blob);
        }
      }, mime, quality);
    });
  }

  // small helper: navigate to an URL but fetch & render its HTML first so Django messages
  // present in the server-rendered HTML appear correctly.
  // If fetch fails, fallback to normal navigation.
  async function navigateAndRender(url) {
    try {
      // fetch with same-origin credentials so session/cookies/messages are included
      const resp = await fetch(url, { credentials: 'same-origin', method: 'GET', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (!resp.ok) {
        // fallback to standard navigation on non-OK response
        window.location.assign(url);
        return;
      }
      const html = await resp.text();

      // Replace the current document with the fetched HTML.
      // This preserves the server-rendered content including messages.
      // Update browser URL (replaceState to avoid adding an extra history entry)
      try {
        history.replaceState(null, '', url);
        document.open();
        document.write(html);
        document.close();
      } catch (err) {
        // if anything goes wrong, fallback to standard navigation
        window.location.assign(url);
      }
    } catch (err) {
      // network/fetch failed: fallback
      window.location.assign(url);
    }
  }

  // Attach handlers to all forms
  function init() {
    const forms = document.querySelectorAll(`form.${FORM_CLASS}`);
    forms.forEach(form => setupForm(form));
  }

  function setupForm(form) {
    // Map input element -> { blob, filename, originalFileSize, compressedSize }
    const compressedMap = new Map();

    // Find file inputs inside the form
    const fileInputs = Array.from(form.querySelectorAll(`input[type=file].${FILE_INPUT_CLASS}`));

    fileInputs.forEach(input => {
      // Optional preview element creation (modified to support revocation)
      const preview = document.createElement('img');
      preview.style = 'max-width:200px; display:none; margin-top:6px; border:1px solid #ddd; padding:4px;';
      input.insertAdjacentElement('afterend', preview);

      // info text for size (ensure white text)
      let info = null;

      input.addEventListener('change', async (e) => {
        const f = e.target.files && e.target.files[0];
        // revoke previous preview URL if any
        if (preview._url) {
          try { URL.revokeObjectURL(preview._url); } catch (err) { /*ignore*/ }
          preview._url = null;
        }
        if (info && info._url) {
          try { URL.revokeObjectURL(info._url); } catch (err) { /*ignore*/ }
          info._url = null;
        }

        if (!f) {
          compressedMap.delete(input);
          preview.style.display = 'none';
          if (info) info.textContent = '';
          return;
        }

        // immediate preview of original
        preview._url = URL.createObjectURL(f);
        preview.src = preview._url;
        preview.style.display = '';

        try {
          const blob = await resizeAndConvert(f);
          // if blob is null treat as failure
          if (!blob) throw new Error('Conversion returned empty blob');

          // keep suggested filename based on original
          const originalName = f.name || 'photo';
          const base = originalName.includes('.') ? originalName.substring(0, originalName.lastIndexOf('.')) : originalName;
          const ext = blob.type === 'image/webp' ? 'webp' : (blob.type === 'image/jpeg' ? 'jpg' : 'img');
          const filename = base + '.' + ext;

          compressedMap.set(input, {
            blob,
            filename,
            originalSize: f.size,
            compressedSize: blob.size
          });

          // update preview to compressed version (revoke previous objectURL)
          if (preview._url) {
            try { URL.revokeObjectURL(preview._url); } catch (err) { /*ignore*/ }
            preview._url = null;
          }
          preview._url = URL.createObjectURL(blob);
          preview.src = preview._url;

          // add small info text (white)
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

    // Intercepte la soumission du formulaire
    form.addEventListener('submit', (ev) => {
      // If no file inputs with our class, do nothing special
      if (fileInputs.length === 0) return;

      ev.preventDefault();
      // Build FormData from form (includes csrf token and all fields)
      const fd = new FormData(form);

      // Replace file fields with compressed blobs if available
      fileInputs.forEach(input => {
        const name = input.name;
        if (!name) return;
        const entry = compressedMap.get(input);
        if (entry && entry.blob) {
          // delete existing entries for this name and append compressed blob with same name
          fd.delete(name);
          fd.append(name, entry.blob, entry.filename);
        }
        // else leave original file in formdata (browser kept it when constructing fd)
      });

      // Prepare UI progress
      const prog = createProgressElements(form);
      prog.bar.style.width = '0%';
      prog.text.textContent = '';
      // ensure progress text white
      prog.text.className = 'text-white';
      prog.container.style.display = '';

      // Send via XHR so we have upload progress
      const xhr = new XMLHttpRequest();
      const action = form.getAttribute('action') || window.location.href;
      const method = (form.getAttribute('method') || 'POST').toUpperCase();
      xhr.open(method, action, true);

      // CSRF header support
      const csrftoken = getCookie('csrftoken') || form.querySelector('[name=csrfmiddlewaretoken]')?.value;
      if (csrftoken) xhr.setRequestHeader('X-CSRFToken', csrftoken);

      // Important: mark request as AJAX for server detection (useful if you implement Solution B)
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

      // Disable form controls while uploading
      const controls = Array.from(form.querySelectorAll('input,button,textarea,select'));
      controls.forEach(c => c.disabled = true);

      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          const pct = Math.round((ev.loaded / ev.total) * 100);
          prog.bar.style.width = pct + '%';
          prog.text.textContent = `${pct}%`;
          // keep text white
          prog.text.className = 'text-white';
        }
      };

      // ---------------------------
      // Remplacement du xhr.onload
      // ---------------------------
      xhr.onload = async () => {
        controls.forEach(c => c.disabled = false);

        let handled = false;

        // 1) Essayer de lire un JSON contenant {"redirect": "..."}
        try {
          const data = JSON.parse(xhr.responseText || '{}');
          if (data && data.redirect) {
            // use navigateAndRender to fetch the redirected page and render it so messages appear
            await navigateAndRender(data.redirect);
            handled = true;
            return;
          }
        } catch (err) {
          // pas JSON -> on continue
        }

        // 2) Si le serveur renvoie une redirection 3xx (souvent 302)
        if (!handled && xhr.status >= 300 && xhr.status < 400) {
          const loc = xhr.getResponseHeader('Location');
          if (loc) {
            await navigateAndRender(loc);
            handled = true;
            return;
          }
        }

        // 3) xhr.responseURL = URL finale que le serveur a renvoyée
        // (Chrome/Firefox peuvent exposer la destination finale)
        if (!handled && xhr.responseURL) {
          const initial = (action || window.location.href).split('#')[0];
          const final = xhr.responseURL.split('#')[0];

          if (final && final !== initial) {
            await navigateAndRender(final);
            handled = true;
            return;
          }
        }

        // 4) Si pas de redirection détectée -> comportement par défaut
        if (!handled && xhr.status >= 200 && xhr.status < 300) {
          prog.bar.style.width = '100%';
          prog.text.textContent = '100% - Téléversement terminé';
          prog.text.className = 'text-white';
          const targetSel = form.getAttribute('data-success-target');
          if (targetSel) {
            const tgt = document.querySelector(targetSel);
            if (tgt) {
              tgt.textContent = 'Téléversement réussi.';
              // make sure the text is white if it's from JS
              tgt.classList && tgt.classList.add('text-white');
            }
          } else {
            // Default fallback
            alert('Téléversement réussi.');
          }
        } else if (!handled) {
          prog.text.textContent = `Erreur upload (${xhr.status})`;
          prog.text.className = 'text-white';
          alert(`Erreur upload (${xhr.status})`);
        }

        // Cleanup: revoke any object URLs created for previews or blobs
        fileInputs.forEach(inp => {
          const prev = inp.nextElementSibling;
          if (prev && prev.tagName === 'IMG' && prev._url) {
            try { URL.revokeObjectURL(prev._url); } catch (err) { /* ignore */ }
            prev._url = null;
          }
        });
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

  // Init on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
