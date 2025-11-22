// client_multi_image_upload.js
(() => {
  // CONFIG
  const MAX_WIDTH = 1200;            
  const QUALITY = 0.75;              
  const OUTPUT_TYPE = 'image/webp';  
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
      try { if (imgBitmap && imgBitmap.close) imgBitmap.close(); } catch (e) { }
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

  function blobToFile(blob, filename) {
    try {
      return new File([blob], filename, { type: blob.type });
    } catch (e) {
      blob.name = filename;
      return blob;
    }
  }

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

  function init() {
    const forms = document.querySelectorAll(`form.${FORM_CLASS}`);
    forms.forEach(form => setupForm(form));
  }

  function setupForm(form) {
    const compressedMap = new Map();
    const fileInputs = Array.from(form.querySelectorAll(`input[type=file].${FILE_INPUT_CLASS}`));

    fileInputs.forEach(input => {
      const preview = document.createElement('img');
      preview.style = 'max-width:200px; display:none; margin-top:6px; border:1px solid #ddd; padding:4px;';
      input.insertAdjacentElement('afterend', preview);

      let info = null;

      input.addEventListener('change', async (e) => {
        const f = e.target.files && e.target.files[0];
        if (preview._url) { try { URL.revokeObjectURL(preview._url); } catch {} preview._url = null; }
        if (compressedMap.get(input)?._url) { try { URL.revokeObjectURL(compressedMap.get(input)._url); } catch {} }

        if (!f) {
          compressedMap.delete(input);
          preview.style.display = 'none';
          if (info) info.textContent = '';
          return;
        }

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

          compressedMap.set(input, [{ blob, filename, originalSize: f.size, compressedSize: blob.size }]);

          if (preview._url) { try { URL.revokeObjectURL(preview._url); } catch {} preview._url = null; }
          preview._url = URL.createObjectURL(blob);
          preview.src = preview._url;

          if (!info) {
            info = document.createElement('div');
            info.className = 'text-white';
            info.style = 'font-size:12px; margin-top:4px; color:inherit';
            input.insertAdjacentElement('afterend', info);
          }
          info.textContent = `Prêt : ${(f.size/1024).toFixed(1)}KB → ${(blob.size/1024).toFixed(1)}KB`;

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

    form.addEventListener('submit', async (ev) => {
      const fileInputs = Array.from(form.querySelectorAll(`input[type=file].${FILE_INPUT_CLASS}`));
      if (fileInputs.length === 0) return;

      const useAjax = form.getAttribute('data-ajax') === '1';

      if (!useAjax) {
        ev.preventDefault();

        const prog = createProgressElements(form);
        prog.bar.style.width = '100%';
        prog.text.textContent = 'Envoi en cours...';
        prog.text.className = 'text-white';
        prog.container.style.display = '';

        try {
          fileInputs.forEach(input => {
            const arr = compressedMap.get(input);
            if (!arr || arr.length === 0) return;
            const dt = new DataTransfer();
            arr.forEach(info => dt.items.add(blobToFile(info.blob, info.filename)));
            input.files = dt.files;
          });

          form.removeEventListener('submit', arguments.callee);
          form.submit();
        } catch {
          const fd = new FormData(form);

          // --- AJOUT CHECKBOX CLEAR ---
          form.querySelectorAll('input[type="checkbox"][name$="-clear"]').forEach(cb => {
            if (cb.checked && !fd.has(cb.name)) fd.append(cb.name, 'on');
          });

          fileInputs.forEach(input => {
            const arr = compressedMap.get(input);
            if (arr && arr.length) {
              fd.delete(input.name);
              arr.forEach(info => fd.append(input.name, info.blob, info.filename));
            }
          });

          const xhr = new XMLHttpRequest();
          const action = form.getAttribute('action') || window.location.href;
          const method = (form.getAttribute('method') || 'POST').toUpperCase();
          xhr.open(method, action, true);
          const csrftoken = getCookie('csrftoken') || form.querySelector('[name=csrfmiddlewaretoken]')?.value;
          if (csrftoken) xhr.setRequestHeader('X-CSRFToken', csrftoken);

          const controls = Array.from(form.querySelectorAll('input,button,textarea,select'));
          controls.forEach(c => c.disabled = true);

          xhr.onload = async () => {
            controls.forEach(c => c.disabled = false);
            if (xhr.responseURL) await navigateAndRender(xhr.responseURL);
            else window.location.reload();
          };
          xhr.onerror = () => { controls.forEach(c => c.disabled = false); alert('Erreur réseau.'); };
          xhr.send(fd);
        }
        return;
      }

      // ---------- AJAX path ----------
      ev.preventDefault();
      const fd = new FormData(form);

      // --- AJOUT CHECKBOX CLEAR ---
      form.querySelectorAll('input[type="checkbox"][name$="-clear"]').forEach(cb => {
        if (cb.checked && !fd.has(cb.name)) fd.append(cb.name, 'on');
      });

      fileInputs.forEach(input => {
        const arr = compressedMap.get(input);
        if (arr && arr.length) {
          fd.delete(input.name);
          arr.forEach(info => fd.append(input.name, info.blob, info.filename));
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
      const csrftoken = getCookie('csrftoken') || form.querySelector('[name=csrfmiddlewaretoken]')?.value;
      if (csrftoken) xhr.setRequestHeader('X-CSRFToken', csrftoken);

      const controls = Array.from(form.querySelectorAll('input,button,textarea,select'));
      controls.forEach(c => c.disabled = true);

      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          const pct = Math.round((ev.loaded / ev.total) * 100);
          prog.bar.style.width = pct + '%';
          prog.text.textContent = `${pct}%`;
        } else {
          prog.textContent = 'Envoi...';
        }
      };

      xhr.onload = async () => {
        controls.forEach(c => c.disabled = false);
        if (xhr.responseURL) { await navigateAndRender(xhr.responseURL); return; }
        if (xhr.status >= 200 && xhr.status < 300) {
          prog.bar.style.width = '100%';
          prog.text.textContent = 'Téléversement terminé';
        } else {
          prog.textContent = `Erreur upload (${xhr.status})`;
          alert(`Erreur upload (${xhr.status})`);
        }
      };

      xhr.onerror = () => { controls.forEach(c => c.disabled = false); prog.textContent = 'Erreur réseau.'; alert('Erreur réseau.'); };

      xhr.send(fd);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
