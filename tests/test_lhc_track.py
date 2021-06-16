import pickle
import json
import pathlib
import numpy as np

import xtrack as xt
import xobjects as xo
import pysixtrack


from xobjects.context import available

test_data_folder = pathlib.Path(
        __file__).parent.joinpath('../test_data').absolute()

def test_lhc_track():
    for fname_line_particles in [
            test_data_folder.joinpath('lhc_no_bb/line_and_particle.json'),
            test_data_folder.joinpath('./hllhc_14/line_and_particle.json')]:

        for CTX in xo.ContextCpu, xo.ContextPyopencl, xo.ContextCupy:
            if CTX not in available:
                continue

            print(f"Test {CTX}")
            context = CTX()

            #############
            # Load file #
            #############

            if str(fname_line_particles).endswith('.pkl'):
                with open(fname_line_particles, 'rb') as fid:
                    input_data = pickle.load(fid)
            elif str(fname_line_particles).endswith('.json'):
                with open(fname_line_particles, 'r') as fid:
                    input_data = json.load(fid)

            ##################
            # Get a sequence #
            ##################

            sequence = pysixtrack.Line.from_dict(input_data['line'])

            ##################
            # Build TrackJob #
            ##################
            print('Build tracker...')
            tracker = xt.Tracker(_context=context, sequence=sequence)

            ######################
            # Get some particles #
            ######################
            part_pyst = pysixtrack.Particles.from_dict(input_data['particle'])

            pysixtrack_particles = [part_pyst, part_pyst] # Track twice the same particle

            particles = xt.Particles(pysixtrack_particles=pysixtrack_particles,
                                     _context=context)
            #########
            # Track #
            #########
            print('Track a few turns...')
            n_turns = 10
            tracker.track(particles, num_turns=n_turns)

            ############################
            # Check against pysixtrack #
            ############################
            print('Check against pysixtrack...')
            ip_check = 1
            vars_to_check = ['x', 'px', 'y', 'py', 'zeta', 'delta', 's']
            pyst_part = pysixtrack_particles[ip_check].copy()
            for _ in range(n_turns):
                sequence.track(pyst_part)

            for vv in vars_to_check:
                pyst_value = getattr(pyst_part, vv)
                xt_value = context.nparray_from_context_array(getattr(particles, vv))[ip_check]
                passed = np.isclose(xt_value, pyst_value, rtol=1e-9, atol=1e-11)
                if not passed:
                    print(f'Not passend on var {vv}!\n'
                          f'    pyst:   {pyst_value: .7e}\n'
                          f'    xtrack: {xt_value: .7e}\n')
                    raise ValueError

            ##############
            # Check  ebe #
            ##############
            print('Check element-by-element against pysixtrack...')
            pyst_part = pysixtrack_particles[ip_check].copy()
            vars_to_check = ['x', 'px', 'y', 'py', 'zeta', 'delta', 's']
            problem_found = False
            for ii, (eepyst, nn) in enumerate(zip(sequence.elements, sequence.element_names)):
                vars_before = {vv :getattr(pyst_part, vv) for vv in vars_to_check}
                particles.set_particles_from_pysixtrack(ip_check, pyst_part)

                tracker.track(particles, ele_start=ii, num_elements=1)

                eepyst.track(pyst_part)
                for vv in vars_to_check:
                    pyst_change = getattr(pyst_part, vv) - vars_before[vv]
                    xt_change = context.nparray_from_context_array(
                            getattr(particles, vv))[ip_check] -vars_before[vv]
                    passed = np.isclose(xt_change, pyst_change, rtol=1e-10, atol=5e-14)
                    if not passed:
                        problem_found = True
                        print(f'\nelement {nn}')
                        print(f'Not passend on var {vv}!\n'
                              f'    pyst:   {pyst_change: .7e}\n'
                              f'    xtrack: {xt_change: .7e}\n')
                        break

                if not passed:
                    break
                else:
                    print(f'Check passed for element: {nn}        ', end='\r', flush=True)

            assert not(problem_found)

            if not problem_found:
                print('All passed on context:')
                print(context)

