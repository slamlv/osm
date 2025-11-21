// client_multi_image_upload.js
(() => {
  // CONFIG
  const MAX_WIDTH = 1200;            // largeur max en px
  const QUALITY = 0.8;               // 0.0 -> 1.0
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
    bar.style = 'height:10px; width:0%';
    barwrap.appendChild(bar);

    const text = document.createElement('div');
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
    const img = await new Promise((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = rej;
      i.src = URL.createObjectURL(file);
    });

    // compute new size
    let targetWidth = img.width;
    let targetHeight = img.height;
    if (MAX_WIDTH && img.width > MAX_WIDTH) {
      targetWidth = MAX_WIDTH;
      targetHeight = Math.round(img.height * (MAX_WIDTH / img.width));
    }

    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, targetWidth, targetHeight);

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
      // Optional preview element creation
      const preview = document.createElement('img');
      preview.style = 'max-width:200px; display:none; margin-top:6px; border:1px solid #ddd; padding:4px;';
      input.insertAdjacentElement('afterend', preview);

      input.addEventListener('change', async (e) => {
        const f = e.target.files && e.target.files[0];
        if (!f) {
          compressedMap.delete(input);
          preview.style.display = 'none';
          return;
        }

        // show immediate preview of original
        preview.src = URL.createObjectURL(f);
        preview.style.display = '';

        try {
          const blob = await resizeAndConvert(f);
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

          // update preview to compressed version
          preview.src = URL.createObjectURL(blob);

          // add small info text
          let info = input._clientInfo;
          if (!info) {
            info = document.createElement('div');
            info.style = 'font-size:12px; margin-top:4px; color:#333';
            input.insertAdjacentElement('afterend', info);
            input._clientInfo = info;
          }
          info.textContent = `Prêt : ${ (f.size/1024).toFixed(1) }KB → ${ (blob.size/1024).toFixed(1) }KB`;
        } catch (err) {
          console.error('Erreur traitement image:', err);
          compressedMap.delete(input);
          preview.style.display = 'none';
          if (input._clientInfo) input._clientInfo.textContent = 'Erreur lors du traitement côté client';
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
      prog.container.style.display = '';

      // Send via XHR so we have upload progress
      const xhr = new XMLHttpRequest();
      const action = form.getAttribute('action') || window.location.href;
      const method = (form.getAttribute('method') || 'POST').toUpperCase();
      xhr.open(method, action, true);

      // CSRF header support
      const csrftoken = getCookie('csrftoken') || form.querySelector('[name=csrfmiddlewaretoken]')?.value;
      if (csrftoken) xhr.setRequestHeader('X-CSRFToken', csrftoken);

      // Disable form controls while uploading
      const controls = Array.from(form.querySelectorAll('input,button,textarea,select'));
      controls.forEach(c => c.disabled = true);

      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          const pct = Math.round((ev.loaded / ev.total) * 100);
          prog.bar.style.width = pct + '%';
          prog.text.textContent = `${pct}%`;
        }
      };

      xhr.onload = () => {
        controls.forEach(c => c.disabled = false);
        if (xhr.status >= 200 && xhr.status < 300) {
          prog.bar.style.width = '100%';
          prog.text.textContent = '100% - Téléversement terminé';
          // Option: si la vue renvoie JSON {redirect: "..."} on peut rediriger
          try {
            const data = JSON.parse(xhr.responseText || '{}');
            if (data.redirect) {
              window.location.href = data.redirect;
              return;
            }
          } catch (e) { /* non-json, ignore */ }
          // sinon afficher un petit message
          // si form a data-success-target, injecter la réponse dedans
          const targetSel = form.getAttribute('data-success-target');
          if (targetSel) {
            const tgt = document.querySelector(targetSel);
            if (tgt) tgt.textContent = 'Téléversement réussi.';
          } else {
            alert('Téléversement réussi.');
          }
        } else {
          prog.text.textContent = `Erreur upload (${xhr.status})`;
          alert(`Erreur upload (${xhr.status})`);
        }
      };

      xhr.onerror = () => {
        controls.forEach(c => c.disabled = false);
        prog.text.textContent = 'Erreur réseau pendant l\'upload.';
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
