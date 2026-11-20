function EEG = ica_decompose(EEG, algorithm)
% ICA_DECOMPOSE  在批处理环境中执行 ICA。
%
%   为什么不直接用 pop_runica：
%   EEGLAB 13 的 pop_runica 在 MATLAB 上会强制给 runica 加上 'interupt','on'，
%   从而创建“点击中断”图形按钮；而新版 MATLAB 的 figure 句柄是对象而不是数值，
%   supergui 收到非数值 figure 会报 “argument 'fig' must be numeric”。
%   批处理环境不需要中断按钮，这里直接调用 runica 并写回标准字段。
%   在当前调用参数下，结果可经 icawinv 重构回原数据；与 pop_runica 的
%   runica 分支是否逐元素一致，本项目未做逐点比对，不作等价性断言。
%
%   pca 分支没有图形依赖，仍交给 pop_runica，避免重复实现其降维逻辑。

if nargin < 2 || isempty(algorithm)
    algorithm = 'runica';
end

switch lower(algorithm)
    case 'runica'
        X = double(reshape(EEG.data, EEG.nbchan, []));
        [weights, sphere] = runica(X, 'extended', 1);
        EEG.icaweights = weights;
        EEG.icasphere = sphere;
        EEG.icachansind = 1:EEG.nbchan;
        EEG.icawinv = [];
        EEG = eeg_checkset(EEG);

    case 'pca'
        EEG = pop_runica(EEG, 'icatype', 'pca');

    otherwise
        error('EEGLAB_MCP:BadParams', 'Unsupported ICA algorithm: %s', algorithm);
end
end
