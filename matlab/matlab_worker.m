function matlab_worker(workdir, idle_timeout_s)
% MATLAB_WORKER 常驻工作进程：轮询作业目录，避免每次调用重新冷启动。
%
%   协议（全部基于文件，无 stdin，兼容 matlab -batch）：
%     req_<id>.json  由 Python 写入，内容与 run_job 的 job 文件相同
%     res_<id>.json  由本进程写出
%     __shutdown__   出现即退出
%
%   用法：matlab -batch "matlab_worker('C:/.../worker',600)"

if nargin < 2, idle_timeout_s = 600; end
addpath(fileparts(mfilename('fullpath')));

if exist(workdir, 'dir') ~= 7
    mkdir(workdir);
end

last_active = tic;
while true
    if exist(fullfile(workdir, '__shutdown__'), 'file')
        break;
    end

    reqs = dir(fullfile(workdir, 'req_*.json'));
    if isempty(reqs)
        if toc(last_active) > idle_timeout_s
            break;
        end
        pause(0.05);
        continue;
    end

    last_active = tic;
    name = reqs(1).name;
    token = regexprep(name, '^req_', '');
    token = regexprep(token, '\.json$', '');
    req_file = fullfile(workdir, name);
    job_file = fullfile(workdir, ['job_' token '.json']);
    res_file = fullfile(workdir, ['res_' token '.json']);

    try
        movefile(req_file, job_file);
    catch
        continue;   % 另一个消费者已取走
    end

    try
        run_job(job_file, res_file);
    catch ME
        r = struct('ok', false, 'action', 'worker', ...
            'error', struct('code', 'WORKER_ERROR', 'message', ME.message), ...
            'warnings', {{}}, 'artifacts', {{}}, 'data', struct());
        fid = fopen(res_file, 'w', 'n', 'UTF-8');
        if fid >= 0
            fwrite(fid, jsonencode(r), 'char');
            fclose(fid);
        end
    end
    if exist(job_file, 'file'), delete(job_file); end
end
end
