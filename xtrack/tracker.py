from pathlib import Path
import numpy as np

from .particles import Particles, gen_local_particle_api
from .general import _pkg_root
from .line import Line

import xobjects as xo

api_conf = {'prepointer': ' /*gpuglmem*/ '}

class Tracker:

    def __init__(self, _context, sequence,
            particles_class=None,
            particles_monitor_class=None,
            global_xy_limit=1.,
            local_particle_src=None,
            save_source_as=None):

        if particles_class is None:
            import xtrack as xt # I have to do it like this 
                                # to avoid circular import
            particles_class = xt.Particles

        if particles_monitor_class is None:
            import xtrack as xt # I have to do it like this 
                                # to avoid circular import
            particles_monitor_class = xt.ParticlesMonitor

        self.global_xy_limit = global_xy_limit

        line = Line(_context=_context, sequence=sequence)

        sources = []
        kernels = {}
        cdefs = []

        sources.append(f'#define XTRACK_GLOBAL_POSLIMIT ({global_xy_limit})')
        sources.append(_pkg_root.joinpath('headers/constants.h'))

        # Particles
        source_particles, kernels_particles, cdefs_particles = (
                                    particles_class.XoStruct._gen_c_api(conf=api_conf))
        sources.append(source_particles)
        kernels.update(kernels_particles)
        cdefs += cdefs_particles.split('\n')

        # Local particles
        if local_particle_src is None:
            local_particle_src = gen_local_particle_api()
        sources.append(local_particle_src)

        # Elements
        element_classes = line._ElementRefClass._rtypes + (
                               particles_monitor_class.XoStruct,)
        for cc in element_classes:
            ss, kk, dd = cc._gen_c_api(conf=api_conf)
            sources.append(ss)
            kernels.update(kk)
            cdefs += dd.split('\n')

            sources += cc.extra_sources

        sources.append(_pkg_root.joinpath('tracker_src/tracker.h'))

        cdefs_norep=[] # TODO Check if this can be handled be the context
        for cc in cdefs:
            if cc not in cdefs_norep:
                cdefs_norep.append(cc)

        src_lines = []
        src_lines.append(r'''
            /*gpukern*/
            void track_line(
                /*gpuglmem*/ int8_t* buffer,
                /*gpuglmem*/ int64_t* ele_offsets,
                /*gpuglmem*/ int64_t* ele_typeids,
                             ParticlesData particles,
                             int num_turns,
                             int ele_start,
                             int num_ele_track,
                             int flag_tbt_monitor,
                /*gpuglmem*/ int8_t* buffer_tbt_monitor,
                             int64_t offset_tbt_monitor){


            LocalParticle lpart;

            int64_t part_id = 0;                    //only_for_context cpu_serial cpu_openmp
            int64_t part_id = blockDim.x * blockIdx.x + threadIdx.x; //only_for_context cuda
            int64_t part_id = get_global_id(0);                    //only_for_context opencl


            /*gpuglmem*/ int8_t* tbt_mon_pointer =
                            buffer_tbt_monitor + offset_tbt_monitor;
            ParticlesMonitorData tbt_monitor =
                            (ParticlesMonitorData) tbt_mon_pointer;

            int64_t n_part = ParticlesData_get_num_particles(particles);
            if (part_id<n_part){
            Particles_to_LocalParticle(particles, &lpart, part_id);

            for (int64_t iturn=0; iturn<num_turns; iturn++){

                if (check_is_not_lost(&lpart)>0){
                    update_at_turn(&lpart, iturn);

                    if (flag_tbt_monitor){
                        ParticlesMonitor_track_local_particle(tbt_monitor, &lpart);
                    }
                }

                for (int64_t ee=ele_start; ee<ele_start+num_ele_track; ee++){
                    if (check_is_not_lost(&lpart)>0){

                        update_at_element(&lpart, ee);

                        /*gpuglmem*/ int8_t* el = buffer + ele_offsets[ee];
                        int64_t ee_type = ele_typeids[ee];

                        switch(ee_type){
        ''')

        for ii, cc in enumerate(element_classes):
            ccnn = cc.__name__.replace('Data', '')
            src_lines.append(f'''
                        case {ii}:
''')
            if ccnn == 'Drift':
                src_lines.append('''
                            global_aperture_check(&lpart);

                            ''')
            src_lines.append(
f'''
                            {ccnn}_track_local_particle(({ccnn}Data) el, &lpart);
                            break;''')

        src_lines.append('''
                        } //switch
                    } // check_is_not_lost
                } // for elements
            } // for turns
            }// if partid
        }//kernel
        ''')

        source_track = '\n'.join(src_lines)
        sources.append(source_track)

        for ii, ss in enumerate(sources):
            if isinstance(ss, Path):
                with open(ss, 'r') as fid:
                    ss = fid.read()
            sources[ii] = ss.replace('/*gpufun*/', '/*gpufun*/ static inline')

        kernel_descriptions = {
            "track_line": xo.Kernel(
                args=[
                    xo.Arg(xo.Int8, pointer=True, name='buffer'),
                    xo.Arg(xo.Int64, pointer=True, name='ele_offsets'),
                    xo.Arg(xo.Int64, pointer=True, name='ele_typeids'),
                    xo.Arg(particles_class.XoStruct, name='particles'),
                    xo.Arg(xo.Int32, name='num_turns'),
                    xo.Arg(xo.Int32, name='ele_start'),
                    xo.Arg(xo.Int32, name='num_ele_track'),
                    xo.Arg(xo.Int32, name='flag_tbt_monitor'),
                    xo.Arg(xo.Int8, pointer=True, name='buffer_tbt_monitor'),
                    xo.Arg(xo.Int64, name='offset_tbt_monitor'),
                ],
            )
        }

        # Internal API can be exposed only on CPU
        if not isinstance(_context, xo.ContextCpu):
            kernels = {}
        kernels.update(kernel_descriptions)

        # Compile!
        _context.add_kernels(sources, kernels, extra_cdef='\n\n'.join(cdefs_norep),
                            save_source_as=save_source_as,
                            specialize=True)

        ele_offsets = np.array([ee._offset for ee in line.elements], dtype=np.int64)
        ele_typeids = np.array(
                [element_classes.index(ee._xobject.__class__) for ee in line.elements],
                dtype=np.int64)
        ele_offsets_dev = _context.nparray_to_context_array(ele_offsets)
        ele_typeids_dev = _context.nparray_to_context_array(ele_typeids)

        self._context = _context
        self.particles_class = particles_class
        self.particles_monitor_class = particles_monitor_class
        self.ele_offsets_dev = ele_offsets_dev
        self.ele_typeids_dev = ele_typeids_dev
        self.track_kernel = _context.kernels.track_line
        self.num_elements = len(line.elements)
        self.line = line


    def track(self, particles, ele_start=0, num_elements=None, num_turns=1,
              turn_by_turn_monitor=None):

        if num_elements is None:
            num_elements = self.num_elements

        assert num_elements + ele_start <= self.num_elements

        if turn_by_turn_monitor is None or turn_by_turn_monitor is False:
            flag_tbt = 0
            buffer_monitor = particles._buffer.buffer # I just need a valid buffer
            offset_monitor = 0
        elif turn_by_turn_monitor is True:
            flag_tbt = 1
            # TODO Assumes at_turn starts from zero, to be generalized
            monitor = self.particles_monitor_class(_context=self._context,
                    start_at_turn=0, stop_at_turn=num_turns,
                    num_particles=particles.num_particles)
            buffer_monitor = monitor._buffer.buffer
            offset_monitor = monitor._offset
        else:
            raise NotImplementedError
            # User can provide their own monitor

        self.track_kernel.description.n_threads = particles.num_particles
        self.track_kernel(
                buffer=self.line._buffer.buffer,
                ele_offsets=self.ele_offsets_dev,
                ele_typeids=self.ele_typeids_dev,
                particles=particles._xobject,
                num_turns=num_turns,
                ele_start=ele_start,
                num_ele_track=num_elements,
                flag_tbt_monitor=flag_tbt,
                buffer_tbt_monitor=buffer_monitor,
                offset_tbt_monitor=offset_monitor)

        if flag_tbt:
            self.record_last_track = monitor
        else:
            self.record_last_track = None

