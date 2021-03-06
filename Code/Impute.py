import numpy as np
import os, sys
import time
import h5py
import torch
import torch.nn.functional as F
from Higashi_backend.utils import get_config, generate_binpair

def impute_process(config_path, model, name, mode):
	config = get_config(config_path)
	
	res = config['resolution']
	impute_list = config['impute_list']
	chrom_list = config['chrom_list']
	temp_dir = config['temp_dir']
	min_distance = config['minimum_distance']
	if min_distance < 0:
		min_bin = 0
	else:
		min_bin = int(min_distance / res)
	max_distance = config['maximum_distance']
	if max_distance < 0:
		max_bin = 1e5
	else:
		max_bin = int(max_distance / res)
	
	num = np.load(os.path.join(temp_dir, "num.npy"))
	num_list = np.cumsum(num)
	
	model.eval()
	with torch.no_grad():
		try:
			model.encode1.dynamic_nn.start_fix()
		except:
			print("cannot start fix")
			pass
	start = time.time()
	chrom2info = {}
	big_samples = []
	bin_ids = []
	slice_start = 0
	for chrom in impute_list:
		j = chrom_list.index(chrom)
		bin_ids.append(np.arange(num_list[j], num_list[j + 1]) + 1)
		if "minimum_impute_distance" in config:
			min_bin_ = int(config["minimum_impute_distance"] / res)
		else:
			min_bin_ = min_bin
		
		if "maximum_impute_distance" in config:
			if config["maximum_impute_distance"] < 0:
				max_bin_ = int(1e5)
			else:
				max_bin_ = int(config["maximum_impute_distance"] / res)
		else:
			max_bin_ = max_bin
		
		samples_bins = generate_binpair( start=num_list[j], end=num_list[j + 1],
		                                min_bin_=min_bin_, max_bin_=max_bin_)
		
		samples = samples_bins - int(num_list[j]) - 1
		xs = samples[:, 0]
		ys = samples[:, 1]
		
		
		if mode == 'classification':
			activation = torch.sigmoid
		elif mode == 'rank':
			activation = F.softplus
		else:
			activation = F.softplus
		samples = np.concatenate([np.ones((len(samples_bins), 1), dtype='int'), samples_bins],
		                         axis=-1)
		f = h5py.File(os.path.join(temp_dir, "%s_%s.hdf5" % (chrom, name)), "w")
		to_save = np.stack([xs, ys], axis=-1)
		f.create_dataset("coordinates", data=to_save)
		big_samples.append(samples)
		chrom2info[chrom] = [slice_start, slice_start + len(samples), f]
		slice_start += len(samples)
		
	print(chrom2info)
	big_samples = np.concatenate(big_samples, axis=0)
	bin_ids = np.concatenate(bin_ids, axis=0)
	model.eval()
	
	with torch.no_grad():
		for i in range(num[0]):
			cell = i + 1
			model.encode1.dynamic_nn.fix_cell(cell, bin_ids)
			
			big_samples[:, 0] = cell
			proba = model.predict(big_samples, verbose=False, batch_size=int(3e4),
			                      activation=activation).reshape((-1))
			
			for chrom in impute_list:
				slice_start, slice_end, f = chrom2info[chrom]
				f.create_dataset("cell_%d" % (i), data=proba[slice_start:slice_end])
			if i % 10 == 0:
				print("Imputing %s: %d of %d" % (name, i, num[0]))
	
	print("finish writing, used %.2f s" % (time.time() - start))
	model.train()
	model.encode1.dynamic_nn.fix = False
	f.close()


def get_free_gpu():
	os.system('nvidia-smi -q -d Memory |grep -A4 GPU|grep Free > ./tmp')
	memory_available = [int(x.split()[2]) for x in open('tmp', 'r').readlines()]
	if len(memory_available) > 0:
		id = int(np.argmax(memory_available))
		print("setting to gpu:%d" % id)
		torch.cuda.set_device(id)
		return "cuda:%d" % id
	else:
		return


if __name__ == '__main__':
	
	if torch.cuda.is_available():
		current_device = get_free_gpu()
	else:
		current_device = 'cpu'
	
	device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
	config_path, path, name, mode = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
	model = torch.load(path, map_location=current_device)
	print(config_path, path, name, mode)
	impute_process(config_path, model, name, mode)