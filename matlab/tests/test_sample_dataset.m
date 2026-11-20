function results = test_sample_dataset()
% TEST_SAMPLE_DATASET  在 EEGLAB 自带真实数据上跑通分段与 ERP。
%
%   合成数据验证“算法对不对”，真实数据验证“在这台机器的这套 EEGLAB 上
%   确实能读、能分段、能算频谱”。两者不能互相替代。

results = struct('name', {}, 'passed', {}, 'detail', {});
root = getenv('EEGLAB_ROOT');
if isempty(root)
    error('EEGLAB_MCP:NoRoot', 'Set EEGLAB_ROOT to your EEGLAB installation.');
end
f = fullfile(root, 'sample_data', 'eeglab_data.set');

if exist(f, 'file') ~= 2
    results(end + 1) = mcp_check('sample:available', true, ...
        ['跳过：未找到 ' f '（可用 EEGLAB_ROOT 指定）']);
    return
end

try
    EEG = pop_loadset('filename', 'eeglab_data.set', ...
                      'filepath', fullfile(root, 'sample_data'));
    results(end + 1) = mcp_check('sample:load', ...
        EEG.nbchan == 32 && abs(EEG.srate - 128) < 1e-9, ...
        sprintf('%d 通道，%g Hz，%d 个事件', EEG.nbchan, EEG.srate, numel(EEG.event)));

    E = pop_epoch(EEG, {'square'}, [-0.2 0.8]);
    results(end + 1) = mcp_check('sample:epoch', E.trials > 0, ...
        sprintf('在 square 事件上得到 %d 个试次', E.trials));

    B = pop_rmbase(E, [-200 0]);
    erp = mean(B.data, 3);
    results(end + 1) = mcp_check('sample:erp_finite', all(isfinite(erp(:))), ...
        sprintf('ERP 矩阵 %s 全部有限', mat2str(size(erp))));

    [spectra, freqs] = spectopo(reshape(EEG.data, EEG.nbchan, []), 0, EEG.srate, ...
                                'plot', 'off');
    results(end + 1) = mcp_check('sample:psd_finite', ...
        all(isfinite(spectra(:))) && numel(freqs) == size(spectra, 2), ...
        sprintf('频谱 %s，频点 %d 个', mat2str(size(spectra)), numel(freqs)));
catch ME
    results(end + 1) = mcp_check('sample:load', false, ME.message);
end
end
