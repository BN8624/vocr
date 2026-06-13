(() => {
  const message = document.getElementById('mapping-message');

  const postJson = async (url, payload) => {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'save failed');
    return result;
  };

  const collectMappingPayload = () => {
    const panel = document.querySelector('.mapping-panel');
    const columns = [...document.querySelectorAll('.mapping-column')].map(card => {
      const select = card.querySelector('select');
      return {
        column_id: card.dataset.columnId || '',
        header: card.querySelector('h4')?.textContent || '',
        suggested_field: card.dataset.originalField || '',
        selected_field: select?.value || ''
      };
    });
    return {
      schema_version: '1.0',
      status: 'user_confirmed_save_request',
      created_at: new Date().toISOString(),
      mapping_path: panel
        ? new URL(panel.dataset.mappingPath || 'merged/mapping_suggestions.json', window.location.href).pathname
        : '',
      table_groups: [{ group_id: 'columns', columns }]
    };
  };

  const saveMappingButton = document.getElementById('save-mapping');
  if (saveMappingButton) {
    saveMappingButton.addEventListener('click', async () => {
      if (message) message.textContent = '저장 중입니다...';
      try {
        const result = await postJson('/api/mapping-profile', collectMappingPayload());
        if (message) {
          message.textContent = result.refresh?.ok ? '저장했고 Excel을 갱신했습니다.' : '저장했습니다.';
        }
      } catch (error) {
        if (message) message.textContent = '저장에 실패했습니다.';
      }
    });
  }

  document.querySelectorAll('.crop-control input[type="range"]').forEach(input => {
    const output = input.closest('.crop-control')?.querySelector('output');
    const update = () => {
      if (output) output.textContent = `${input.value}%`;
      const panel = input.closest('.crop-controls');
      const figure = panel?.closest('.page-image');
      const field = input.dataset.ratioField || '';
      const line = figure?.querySelector(`.crop-overlay-line[data-overlay-field="${field}"]`);
      if (line) line.style.top = `${input.value}%`;
    };
    input.addEventListener('input', update);
    update();
  });

  document.querySelectorAll('.save-page-crop').forEach(button => {
    button.addEventListener('click', async () => {
      const panel = button.closest('.crop-controls');
      const messageEl = panel?.querySelector('.page-crop-message');
      if (!panel) return;
      const crop = {};
      panel.querySelectorAll('input[data-ratio-field]').forEach(input => {
        crop[input.dataset.ratioField || ''] = Number(input.value) / 100;
      });
      const payload = {
        schema_version: '1.0',
        state_path: new URL(panel.dataset.cropStatePath || 'merged/page_crop_profile.json', window.location.href).pathname,
        page_number: panel.dataset.pageNumber || '',
        crop
      };
      if (messageEl) messageEl.textContent = '저장 중입니다...';
      try {
        await postJson('/api/page-crop-profile', payload);
        if (messageEl) messageEl.textContent = '저장했습니다.';
      } catch (error) {
        if (messageEl) messageEl.textContent = '저장에 실패했습니다.';
      }
    });
  });

  const checksumButton = document.getElementById('save-checksum-total');
  const checksumMessage = document.getElementById('checksum-message');
  if (checksumButton) {
    checksumButton.addEventListener('click', async () => {
      const container = document.querySelector('.checksum-candidates');
      const selected = document.querySelector('input[name="checksum-total"]:checked');
      if (!container || !selected) {
        if (checksumMessage) checksumMessage.textContent = '합계를 먼저 선택하세요.';
        return;
      }
      let candidate = {};
      try {
        candidate = JSON.parse(selected.dataset.candidate || '{}');
      } catch (error) {
        candidate = {};
      }
      const payload = {
        schema_version: '1.0',
        status: 'user_confirmed_review_state',
        state_path: new URL(container.dataset.statePath || 'merged/review_state.json', window.location.href).pathname,
        checksum: {
          selected_total_id: selected.value,
          selected_total: candidate
        }
      };
      if (checksumMessage) checksumMessage.textContent = '저장 중입니다...';
      try {
        await postJson('/api/review-state', payload);
        if (checksumMessage) checksumMessage.textContent = '저장했습니다.';
      } catch (error) {
        if (checksumMessage) checksumMessage.textContent = '저장에 실패했습니다.';
      }
    });
  }
})();