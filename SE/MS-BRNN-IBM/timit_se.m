function timit_se(test_path, est_path, Tw, Ts, fs, Q)
% TIMIT_SE - speech enhancement with objectice scoring using a MS-BRNN-IBM estimator.
%
% Inputs:
%   test_path - the path to the test files.
%	est_path - path to the IBM estimates.
%   Tw - window length (ms).
%   Ts - window shift (ms).
%   fs - sampling frequency (Hz).
%   Q - SNR values.
%
%% FILE:           timit_se.m 
%% DATE:           2018
%% AUTHOR:         Aaron Nicolson
%% AFFILIATION:    Signal Processing Laboratory, Griffith University
%% BRIEF:          Speech enhancement with objective scoring using a MS-BRNN-IBM estimator.

%% FILE LISTS
x.files = dir([test_path, '/test_clean/*.wav']); % test clean files.
d.files = dir([test_path, '/test_noise/*.wav']); % test noise files.

%% RECORD INPUTS
fid = fopen('par.txt', 'w');
fprintf(fid, 'Tw = %d ms, Ts = %d ms, fs = %d Hz\n', ...
    Tw, Ts, fs); % record inputs.
fprintf(fid, 'Test path: %s\nEstimate path: %s\nSNR values (dB): ', ...
    test_path, est_path); % record paths.
for i = 1:length(Q); fprintf(fid, '%g ', Q(i)); end % dB values.
fclose(fid);

%% LOAD TEST SPEECH INTO MEMORY
for i=1:length(x.files)
    x.files(i).wav = audioread([x.files(i).folder, ...
            '/', x.files(i).name]); % clean test waveform.
end

%% LOAD TEST NOISE INTO MEMORY
for i=1:length(d.files)
    d.files(i).wav = audioread([d.files(i).folder, ...
            '/', d.files(i).name]); % noise test waveform.
end

%% CLEAN
x.Nw = round(fs*Tw*0.001); % window length (samples).
x.Ns = round(fs*Ts*0.001); % window shift (samples).
x.fs = fs; % sampling frequency (Hz).
x.NFFT = 2^nextpow2(x.Nw); % frequency bins (samples).

%% NOISE
d.Nw = round(fs*Tw*0.001); % window length (samples).
d.Ns = round(fs*Ts*0.001); % window shift (samples).
d.fs = fs; % sampling frequency (Hz).
d.NFFT = 2^nextpow2(d.Nw); % frequency bins (samples).

%% NOISY
y.Nw = round(fs*Tw*0.001); % window length (samples).
y.Ns = round(fs*Ts*0.001); % window shift (samples).
y.fs = fs; % sampling frequency (Hz).
y.NFFT = 2^nextpow2(y.Nw); % frequency bins (samples).

%% ESTIMATE
x_hat.Nw = round(fs*Tw*0.001); % window length (samples).
x_hat.Ns = round(fs*Ts*0.001); % window shift (samples).
x_hat.fs = fs; % sampling frequency (Hz).
x_hat.NFFT = 2^nextpow2(x_hat.Nw); % frequency bins (samples).

%% NOISY TEST
fid1 = fopen(strcat('indi.txt'), 'w'); % individual test results.
fid2 = fopen(strcat('avg.txt'), 'w'); % average test results.
for i=1:length(Q)
    ideal.avgSNR = 0; % average SNR for ideal case.
    ideal.avgSegSNR = 0; % average segmental SNR for ideal case.
    ideal.avgWPESQ = 0; % average WPESQ for ideal case.
    ideal.avgQSTI = 0; % average QSTI for ideal case.
    est.avgSNR = 0; % average SNR for estimate case.
    est.avgSegSNR = 0; % average segmental SNR for estimate case.
    est.avgWPESQ = 0; % average WPESQ for estimate case.
    est.avgQSTI = 0; % average QSTI for estimate case.
    for j=1:length(x.files)
        x.wav = x.files(j).wav; % clean waveform.
        d.src = d.files(j).wav; % noise waveform.
        [y.wav, d.wav] = addnoise(x.wav, d.src, Q(i)); % noisy waveform.
        x = analysis_mag(x); % clean magnitude spectrum.
        d = analysis_mag(d); % noise magnitude spectrum.
        y = analysis_mag(y); % noisy magnitude spectrum.
                
        %% IBM SE
        ideal.IBM = x.MAG > d.MAG; % IBM with 0 dB threshold.   
        x_hat.MAG = y.MAG.*ideal.IBM;
        x_hat.PHA = y.PHA;
        x_hat.N = length(x.wav);
        x_hat = synthesis_mag(x_hat); % waveform computed from magnitude spectrum.
        ideal.SNR = segsnr(x.wav, x_hat.wav, fs); % find SegSNR and SNR.
        ideal.WPESQ = pesqbin(x.wav, x_hat.wav, fs, 'wb'); % find Wideband PESQ.
        ideal.QSTI = qsti(x.wav, x_hat.wav, fs); % find QSTI.
    
        %% IBM ESTIMATE SE
        load([est_path, '/', num2str(Q(i)), 'dB/', x.files(j).name(1:end-4), ...
            '_', num2str(Q(i)), 'dB.mat']) % load IBM estimate.
        est.IBM_hat = IBM_hat(1:end-1,:) > 0; % convert to logical.
        x_hat.MAG = y.MAG.*est.IBM_hat;
        x_hat = synthesis_mag(x_hat); % waveform computed from magnitude spectrum.
        est.SNR = segsnr(x.wav, x_hat.wav, fs); % find SegSNR and SNR.
        est.WPESQ = pesqbin(x.wav, x_hat.wav, fs, 'wb'); % find Wideband PESQ.
        est.QSTI = qsti(x.wav, x_hat.wav, fs); % find QSTI.

        %% RECORD RESULTS
        fprintf(fid1, 'file: %s.\n(ESTI.) SNR: %3.2f dB, segSNR: %3.2f, WPESQ: %1.2f, QSTI: %1.2f.\n(IDEAL) SNR: %3.2f dB, segSNR: %3.2f, WPESQ: %1.2f, QSTI: %1.2f.\n', ...
            x.files(j).name, est.SNR.SNR, est.SNR.SNRseg, est.WPESQ, est.QSTI, ideal.SNR.SNR, ideal.SNR.SNRseg, ideal.WPESQ, ideal.QSTI); % individual test results.
        ideal.avgSNR = ideal.avgSNR + ideal.SNR.SNR; % sum of all SNR levels (ideal).
        ideal.avgSegSNR = ideal.avgSegSNR + ideal.SNR.SNRseg; % sum of all segmental SNR levels (ideal).
        ideal.avgWPESQ = ideal.avgWPESQ + ideal.WPESQ; % sum of all WPESQ values (ideal).
        ideal.avgQSTI = ideal.avgQSTI + ideal.QSTI; % sum of all QSTI values (ideal).
        
        est.avgSNR = est.avgSNR + est.SNR.SNR; % sum of all SNR levels (estimate).
        est.avgSegSNR = est.avgSegSNR + est.SNR.SNRseg; % sum of all segmental SNR levels (estimate).
        est.avgWPESQ = est.avgWPESQ + est.WPESQ; % sum of all WPESQ values (estimate).
        est.avgQSTI = est.avgQSTI + est.QSTI; % sum of all QSTI values (estimate).

        clc;
        fprintf('Percentage complete for %ddB: %%%3.2f.\n', Q(i), 100*(j/length(x.files)));
    end
    ideal.avgSNR = ideal.avgSNR/length(x.files);
    ideal.avgSegSNR = ideal.avgSegSNR/length(x.files);
    ideal.avgWPESQ = ideal.avgWPESQ/length(x.files);
    ideal.avgQSTI = ideal.avgQSTI/length(x.files);
    est.avgSNR = est.avgSNR/length(x.files);
    est.avgSegSNR = est.avgSegSNR/length(x.files);
    est.avgWPESQ = est.avgWPESQ/length(x.files);
    est.avgQSTI = est.avgQSTI/length(x.files);

    fprintf(fid2, 'Av. SNR: %2.2fdB (%2.2fdB ideal), av. SegSNR: %2.2fdB (%2.2fdB ideal), av. WPESQ: %1.2f (%1.2f ideal), av. QSTI: %1.2f (%1.2f ideal), SNR: %ddB.\n', ...
    	est.avgSNR, ideal.avgSNR, est.avgSegSNR, ideal.avgSegSNR, est.avgWPESQ, ideal.avgWPESQ, est.avgQSTI, ideal.avgQSTI, Q(i)); % average results.
end
fclose(fid1);
fclose(fid2);
end

