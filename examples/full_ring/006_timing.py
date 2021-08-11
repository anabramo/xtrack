import pathlib
import json
import pickle
import numpy as np

import xtrack as xt
import xobjects as xo
import xline as xl

from make_short_line import make_short_line
import time


test_data_folder = pathlib.Path(
        __file__).parent.joinpath('../../test_data').absolute()

fname_line_particles = test_data_folder.joinpath('lhc_no_bb/line_and_particle.json')
rtol_100turns = 1e-9; atol_100turns=3e-11

# fname_line_particles = test_data_folder.joinpath(
#                                 './lhc_with_bb/line_and_particle.json')
# rtol_100turns = 1e-9; atol_100turns=3e-11

# fname_line_particles = test_data_folder.joinpath(
#                         './hllhc_14/line_and_particle.json')
# rtol_100turns = 1e-9; atol_100turns=3e-11

# fname_line_particles = test_data_folder.joinpath(
#                  './sps_w_spacecharge/line_without_spacecharge_and_particle.json')
# rtol_100turns = 1e-9; atol_100turns=3e-11

#fname_line_particles = test_data_folder.joinpath(
#                   './sps_w_spacecharge/line_with_spacecharge_and_particle.json')
#rtol_100turns = 2e-8; atol_100turns=7e-9

short_test = False
num_turns = int(100)

####################
# Choose a context #
####################

n_part = 8000
context = xo.ContextCpu(omp_num_threads=8)
#context = xo.ContextCpu(omp_num_threads=0)

#n_part = 20000
#context = xo.ContextCupy()

#n_part = 20000
#context = xo.ContextPyopencl('0.0')

#############
# Load file #
#############

if str(fname_line_particles).endswith('.pkl'):
    with open(fname_line_particles, 'rb') as fid:
        input_data = pickle.load(fid)
elif str(fname_line_particles).endswith('.json'):
    with open(fname_line_particles, 'r') as fid:
        input_data = json.load(fid)

# # Force remove bb
# line_dict = input_data['line']
# for ii, ee in enumerate(line_dict['elements']):
#     if ee['__class__'] == 'BeamBeam6D' or ee['__class__'] == 'BeamBeam4D':
#         line_dict['elements'][ii] = {}
#         ee = line_dict['elements'][ii]
#         ee['__class__'] = 'Drift'
#         ee['length'] = 0.

##################
# Get a sequence #
##################

print('Import sequence')
sequence = xl.Line.from_dict(input_data['line'])


#fodo = [xl.Drift(length=1.), xl.Multipole(knl=[0, 1.]),
#        xl.Drift(length=1.), xl.Multipole(knl=[0, -1.])]
#
#elelist = 4000*fodo
#elenames = [f'e{ii}' for ii in range(len(elelist))]
#
#sequence = xl.Line(elements=elelist, element_names=elenames)






if short_test:
    sequence = make_short_line(sequence)

##################
# Build TrackJob #
##################

print('Build tracker')
tracker = xt.Tracker(_context=context,
                     sequence=sequence,
                     save_source_as='source.c')

######################
# Get some particles #
######################

print('Import particles')
part_dict = input_data['particle']

# Go from one particle to many particles
part_dict['x'] += np.linspace(-1e-4, 1e-4, n_part)
part_dict['y'] += np.linspace(-2e-4, 2e-4, n_part)

particles = xt.Particles(_context=context, **part_dict)
#########
# Track #
#########

print('Track!')
print(f'context: {tracker.line._buffer.context}')
t1 = time.time()
tracker.track(particles, num_turns=num_turns)
context.synchronize()
t2 = time.time()
print(f'Time {(t2-t1)*1000:.2f} ms')
print(f'Time {(t2-t1)*1e6/num_turns/n_part:.2f} us/part/turn')


#######################
# Check against xline #
#######################

ip_check = n_part//3*2

print(f'\nTest against xline over {num_turns} turns on particle {ip_check}:')
vars_to_check = ['x', 'px', 'y', 'py', 'zeta', 'delta', 's']

xline_part = xl.Particles(**part_dict)

# Select particle to check
for nn in xline_part._dict_vars:
    if not np.isscalar(getattr(xline_part, nn)):
        setattr(xline_part, nn, getattr(xline_part, nn)[ip_check])

for iturn in range(num_turns):
    print(f'turn {iturn}/{num_turns}', end='\r', flush=True)
    sequence.track(xline_part)

for vv in vars_to_check:
    xline_value = getattr(xline_part, vv)
    xt_value = context.nparray_from_context_array(
                        getattr(particles, vv)[ip_check])
    passed = np.isclose(xt_value, xline_value,
                        rtol=rtol_100turns, atol=atol_100turns)
    if not passed:
        print(f'Not passed on var {vv}!\n'
              f'    xline:   {xline_value: .7e}\n'
              f'    xtrack: {xt_value: .7e}\n')
        raise ValueError
    else:
        print(f'Passed on var {vv}!\n'
              f'    xline:   {xline_value: .7e}\n'
              f'    xtrack: {xt_value: .7e}\n')
