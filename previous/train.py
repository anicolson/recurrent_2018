# FILE:           train.py
# DATE:           2018
# AUTHOR:         Aaron Nicolson
# AFFILIATION:    Signal Processing Laboratory, Griffith University
# BRIEF:          Trains the ResLSTM a-priori SNR estimator, or 'DeepXi'.

import tensorflow as tf
from tensorflow.python.data import Dataset, Iterator
import numpy as np
from datetime import datetime
from scipy.io.wavfile import read
import scipy.io as spio
import feat, os, batch, res, argparse, random, math, time, sys, pickle
np.set_printoptions(threshold=np.nan)

## UPPER ENDPOINT SCALING FACTOR VALUES
# INT	ALPHA
#  10   0.2944
#  20   0.1472
#  30   0.0981
#  40   0.0736
#  50   0.0589

print('ResBLSTM IBM Estimator')

## OPTIONS
version = 'ResBLSTM_IBM_hat' # model version.
train = True # perform training flag.
cont = False # continue from last epoch.
scaling = 0.0981 # scaling factor for SNR dB interval size.
print("Scaling factor: %g." % (scaling))
gpu = "0" # select GPU.
print("%s on GPU:%s." % (version, gpu)) # print version.

## DATASETS
set_loc = ''
train_clean_set = set_loc + '' # path to the clean speech training set.
train_noise_set = set_loc + '' # path to the clean speech training set.
val_clean_set = set_loc + '' # path to the clean speech validation set.
val_noise_set = set_loc + '' # path to the noise validation set.
model_path = '' + version # model save path.
train_clean_list = batch._train_list(train_clean_set, '*.wav', 'clean') # clean speech training list.
train_noise_list = batch._train_list(train_noise_set, '*.wav', 'noise') # noise training list.
if not os.path.exists(model_path): os.makedirs(model_path) # make model path directory.

## NETWORK PARAMETERS
cell_size = 512 # cell size of forward & backward cells.
rnn_depth = 5 # number of RNN layers.
bidirectional = True # use a Bidirectional Recurrent Neural Network.
cell_proj = 256 # output size of the cell projection weight (None for no projection).
residual = 'add' # residual connection either by addition ('add') or concatenation ('concat').
res_proj = None # output size of the residual projection weight (None for no projection).
peepholes = False # use peephole connections.
input_layer = True # use an input layer.
input_size = 512 # size of the input layer output.

## TRAINING PARAMETERS
mbatch_size = 20 # mini-batch size.
max_epochs = 10 # maximum number of epochs.

## FEATURES
snr_list = [-10, -5, 0, 5, 10, 15, 20] # list of SNR levels.
input_dim = 257 # number of inputs.
num_outputs = input_dim # number of output dimensions.
fs = 16000 # sampling frequency (Hz).
Tw = 32 # window length (ms).
Ts = 16 # window shift (ms).
Nw = int(fs*Tw*0.001) # window length (samples).
Ns = int(fs*Ts*0.001) # window shift (samples).
NFFT = int(pow(2, np.ceil(np.log2(Nw)))) # number of DFT components.
nconst = 32768 # normalisation constant (see feat.addnoisepad()).

## GPU CONFIGURATION
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"]=gpu
config = tf.ConfigProto()
config.allow_soft_placement=True
config.gpu_options.allow_growth=True
config.log_device_placement=False

## PLACEHOLDERS
s_ph = tf.placeholder(tf.int16, shape=[None, None]) # clean speech placeholder.
d_ph = tf.placeholder(tf.int16, shape=[None, None]) # noise placeholder.
s_len_ph = tf.placeholder(tf.int32, shape=[None]) # clean speech sequence length placeholder.
d_len_ph = tf.placeholder(tf.int32, shape=[None]) # noise sequence length placeholder.
snr_ph = tf.placeholder(tf.float32, shape=[None]) # SNR placeholder.

## VALIDATION SET
val_clean, val_clean_len, val_snr, _ = batch._test_set(val_clean_set, '*.wav', snr_list) # clean validation waveforms and lengths.
val_noise, val_noise_len, _, _ = batch._test_set(val_noise_set, '*.wav', snr_list) # noise validation waveforms and lengths.

## SNR SET
train_snr_np = np.array(snr_list, np.int32) # training snr levels.
train_snr_d = tf.data.Dataset.from_tensor_slices(np.array(snr_list, np.int32))
train_snr_d = train_snr_d.repeat()
train_snr_d = train_snr_d.shuffle(buffer_size=train_snr_np.shape[0])
train_snr_d = train_snr_d.batch(mbatch_size)
train_snr_i = train_snr_d.make_one_shot_iterator()
train_snr_g = train_snr_i.get_next()

## LOG_10
def log10(x):
  numerator = tf.log(x)
  denominator = tf.constant(np.log(10), dtype=numerator.dtype)
  return tf.div(numerator, denominator)

## FEATURE EXTRACTION FUNCTION
def feat_extr(s, d, s_len, d_len, Q, Nw, Ns, NFFT, fs, P, nconst, scaling):
	'''
	Computes Magnitude Spectrum (MS) input features, and the a priori SNR target.
	The sequences are padded, with seq_len providing the length of each sequence
	without padding.

	Inputs:
		s - clean waveform (dtype=tf.int32).
		d - noisy waveform (dtype=tf.int32).
		s_len - clean waveform length without padding (samples).
		d_len - noise waveform length without padding (samples).
		Q - SNR level.
		Nw - window length (samples).
		Ns - window shift (samples).
		NFFT - DFT components.
		fs - sampling frequency (Hz).
		P - padded waveform length (samples).
		nconst - normalization constant.
		scaling - scaling factor for SNR dB interval size.

	Outputs:
		s_MS - padded noisy single-sided magnitude spectrum.
		xi_dB_mapped - mapped a priori SNR dB.	
		seq_len - length of each sequence without padding.
	'''
	(s, x, d) = tf.map_fn(lambda z: feat.addnoisepad(z[0], z[1], z[2], z[3], z[4],
		P, nconst), (s, d, s_len, d_len, Q), dtype=(tf.float32, tf.float32,
		tf.float32)) # padded noisy waveform, and padded clean waveform.
	seq_len = feat.nframes(s_len, Ns) # length of each sequence.
	s_MS = feat.stms(s, Nw, Ns, NFFT) # clean magnitude spectrum.
	d_MS = feat.stms(d, Nw, Ns, NFFT) # noise magnitude spectrum.
	x_MS = feat.stms(x, Nw, Ns, NFFT) # noisy magnitude spectrum.
	xi = tf.div(tf.square(s_MS), tf.add(tf.square(d_MS), 1e-12)) # a-priori-SNR.
	xi_dB = tf.multiply(10.0, tf.add(log10(xi), 1e-12)) # a-priori-SNR in dB.
	xi_db_mapped = tf.div(1.0, tf.add(1.0, tf.exp(tf.multiply(-scaling, xi_dB)))) # scaled a-priori-SNR.
	xi_db_mapped = tf.boolean_mask(xi_db_mapped, tf.sequence_mask(seq_len)) # convert to 2D.
	return (x_MS, xi_db_mapped, seq_len)

## FEATURE GRAPH
print('Preparing graph...')
P = tf.reduce_max(s_len_ph) # padded waveform length.
feature = feat_extr(s_ph, d_ph, s_len_ph, d_len_ph, snr_ph, Nw, Ns, NFFT, 
	fs, P, nconst, scaling) # feature graph.

## RESNET
parser = argparse.ArgumentParser()
parser.add_argument('--cell_size', default=cell_size, type=int, help='BLSTM cell size.')
parser.add_argument('--rnn_depth', default=rnn_depth, type=int, help='Number of RNN layers.')
parser.add_argument('--bidirectional', default=bidirectional, type=bool, help='Use a Bidirectional Recurrent Neural Network.')
parser.add_argument('--cell_proj', default=cell_proj, type=int, help='Output size of the cell projection matrix (None for no projection).')
parser.add_argument('--res_proj', default=res_proj, type=int, help='Output size of the residual projection matrix (None for no projection).')
parser.add_argument('--residual', default=residual, type=str, help='Residual connection. Either addition or concatenation.')
parser.add_argument('--peepholes', default=peepholes, type=bool, help='Use peephole connections.')
parser.add_argument('--input_layer', default=input_layer, type=bool, help='Use an input layer.')
parser.add_argument('--input_size', default=input_size, type=int, help='Input layer output size.')
parser.add_argument('--verbose', default=True, type=bool, help='Print network.')
parser.add_argument('--parallel_iterations', default=512, type=int, help='Number of parallel iterations.')
args = parser.parse_args()

y_hat = res.ResNet(feature[0], feature[2], num_outputs, args)

## LOSS & OPTIMIZER
loss = res.loss(feature[1], y_hat, 'sigmoid_xentropy')
total_loss = tf.reduce_mean(loss)
trainer, _ = res.optimizer(loss, optimizer='adam')

# SAVE VARIABLES
saver = tf.train.Saver(max_to_keep=256)

## NUMBER OF PARAMETERS
print("No. of trainable parameters: %g." % (np.sum([np.prod(v.get_shape().as_list()) for v in tf.trainable_variables()])))

## TRAINING
if train:
	print("Training...")
	with tf.Session(config=config) as sess:

		## CONTINUE FROM LAST EPOCH
		if cont:
			with open('data/epoch_par_' + version + '.p', 'rb') as f:
				epoch_par = pickle.load(f) # load epoch parameters from last epoch.
			epoch_par['start_idx'] = 0; epoch_par['end_idx'] = mbatch_size # reset start and end index of mini-batch. 
			random.shuffle(train_clean_list) # shuffle list.
			with open('data/epoch_par_' + version + '.p', 'wb') as f:
				pickle.dump(epoch_par, f) # save epoch parameters.
			saver.restore(sess, model_path + '/epoch-' + str(epoch_par['epoch_comp'])) # load model from last epoch.

		## TRAIN RAW NETWORK
		else:
			if os.path.isfile('data/epoch_par_' + version + '.p'):
				os.remove('data/epoch_par_' + version + '.p') # remove epoch parameters.
			print('Creating epoch parameters, as no pickle file exists...')
			epoch_par = {'epoch_size': len(train_clean_list), 'epoch_comp': 0, 
				'start_idx': 0, 'end_idx': mbatch_size, 'val_ce_prev': float("inf")} # create epoch parameters.
			if mbatch_size > epoch_par['epoch_size']:
				raise ValueError('Error: mini-batch size is greater than the epoch size.')
			with open('data/epoch_par_' + version + '.p', 'wb') as f:
				pickle.dump(epoch_par, f) # save epoch parameters.
			sess.run(tf.global_variables_initializer()) # initialise model variables.
			saver.save(sess, model_path + '/epoch', global_step=epoch_par['epoch_comp']) # save model.

		## TRAINING LOG
		if not os.path.exists('log'):
			os.makedirs('log') # create log directory.
		with open("log/val_ce_" + version + ".txt", "a") as results:
			results.write("Validation error, epoch count, D/T.\n")

		while train:
			## MINI-BATCH GENERATION
			train_clean_mbatch, train_clean_mbatch_seq_len = batch._clean_mbatch(train_clean_list, 
				mbatch_size, epoch_par['start_idx'], epoch_par['end_idx'], version) # generate mini-batch of clean training waveforms.
			train_noise_mbatch, train_noise_mbatch_seq_len = batch._noise_mbatch(train_noise_list, 
				mbatch_size, train_clean_mbatch_seq_len) # generate mini-batch of noise training waveforms.
			train_snr_mbatch = sess.run(train_snr_g) # generate mini-batch of SNR levels.

			## TRAINING ITERATION
			sess.run(trainer, feed_dict={s_ph: train_clean_mbatch, d_ph: train_noise_mbatch, 
				s_len_ph: train_clean_mbatch_seq_len, d_len_ph: train_noise_mbatch_seq_len, snr_ph: train_snr_mbatch}) # training iteration.


			print("Epoch %d: %3.2f%%. CE last epoch: %g.                           " % 
				(epoch_par['epoch_comp'] + 1, 100*(epoch_par['end_idx']/epoch_par['epoch_size']), epoch_par['val_ce_prev']), end="\r")

			## UPDATE EPOCH PARAMETERS
			epoch_par['start_idx'] += mbatch_size; epoch_par['end_idx'] += mbatch_size # start and end index of mini-batch.

			## VALIDATION SET CROSS-ENTROPY
			if epoch_par['end_idx'] > epoch_par['epoch_size']:
				random.shuffle(train_clean_list) # shuffle list.
				epoch_par['start_idx'] = 0; epoch_par['end_idx'] = mbatch_size # reset start and end index of mini-batch.
				i = 0; j = mbatch_size; val_flag = True; frames = 0; val_ce = 0; # validation variables.
				while val_flag:
					val_ce_frame = np.mean(sess.run(loss, feed_dict={s_ph: val_clean[i:j], d_ph: val_noise[i:j], 
						s_len_ph: val_clean_len[i:j], d_len_ph: val_noise_len[i:j], snr_ph: val_snr[i:j]}), axis=1) # validation cross-entropy for each frame.
					frames += val_ce_frame.shape[0] # total number of frames.
					val_ce += np.sum(val_ce_frame)
					print("Validation CE for Epoch %d: %3.2f%% complete.       " % 
						(epoch_par['epoch_comp'] + 1, 100*(j/val_clean_len.shape[0])), end="\r")
					i += mbatch_size; j += mbatch_size
					if j > val_clean_len.shape[0]:
						j = val_clean_len.shape[0]
					if i >= val_clean_len.shape[0]:
						val_flag = False
				val_ce /= frames # validation cross-entropy.
				if val_ce < epoch_par['val_ce_prev']:
					epoch_par['val_ce_prev'] = val_ce # lowest validation CE achieved.
					epoch_par['epoch_comp'] += 1 # an epoch has been completed.
					saver.save(sess, model_path + '/epoch', global_step=epoch_par['epoch_comp']) # save model.
					with open("log/val_ce_" + version + ".txt", "a") as results:
						results.write("%g, %d, %s.\n" % (val_ce, epoch_par['epoch_comp'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
					epoch_par['val_flag'] = False # reset validation flag.
					with open('data/epoch_par_' + version + '.p', 'wb') as f:
						pickle.dump(epoch_par, f)
					if epoch_par['epoch_comp'] >= max_epochs:
						train = False
						print('Training complete. Validation CE for epoch %d: %g.                 ' % 
							(epoch_par['epoch_comp'], val_ce))
				else: # exploding gradient.
					saver.restore(sess, model_path + '/epoch-' + str(epoch_par['epoch_comp'])) # load model from last epoch.