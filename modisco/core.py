from __future__ import division, print_function, absolute_import
from collections import OrderedDict
from collections import namedtuple
from collections import defaultdict
import numpy as np
import scipy
import itertools
from . import util


class Snippet(object):

    def __init__(self, fwd, rev, has_pos_axis):
        assert len(fwd)==len(rev),str(len(fwd))+" "+str(len(rev))
        self.fwd = fwd
        self.rev = rev
        self.has_pos_axis = has_pos_axis

    def trim(self, start_idx, end_idx):
        assert end_idx <= len(self)
        assert start_idx >= 0
        new_fwd = self.fwd[start_idx:end_idx]
        new_rev = self.rev[len(self)-end_idx:len(self)-start_idx]
        return Snippet(fwd=new_fwd, rev=new_rev,
                       has_pos_axis=self.has_pos_axis)

    def save_hdf5(self, grp):
        grp.create_dataset("fwd", data=self.fwd)  
        grp.create_dataset("rev", data=self.rev)
        grp.attr["has_pos_axis"] = self.has_pos_axis

    def __len__(self):
        return len(self.fwd)

    def revcomp(self):
        return Snippet(fwd=np.copy(self.rev), rev=np.copy(self.fwd),
                       has_pos_axis=self.has_pos_axis)


class DataTrack(object):

    """
    First dimension of fwd_tracks and rev_tracks should be the example,
    second dimension should be the position (if applicable)
    """
    def __init__(self, name, fwd_tracks, rev_tracks, has_pos_axis):
        self.name = name
        assert len(fwd_tracks)==len(rev_tracks)
        assert len(fwd_tracks[0]==len(rev_tracks[0]))
        self.fwd_tracks = fwd_tracks
        self.rev_tracks = rev_tracks
        self.has_pos_axis = has_pos_axis

    def __len__(self):
        return len(self.fwd_tracks)

    @property
    def track_length(self):
        return len(self.fwd_tracks[0])

    def get_snippet(self, coor):
        if (self.has_pos_axis==False):
            snippet = Snippet(
                    fwd=self.fwd_tracks[coor.example_idx],
                    rev=self.rev_tracks[coor.example_idx],
                    has_pos_axis=self.has_pos_axis)
        else:
            snippet = Snippet(
                    fwd=self.fwd_tracks[coor.example_idx, coor.start:coor.end],
                    rev=self.rev_tracks[
                         coor.example_idx,
                         (self.track_length-coor.end):
                         (self.track_length-coor.start)],
                    has_pos_axis=self.has_pos_axis)
        if (coor.is_revcomp):
            snippet = snippet.revcomp()
        return snippet


class TrackSet(object):

    def __init__(self, data_tracks=[], attribute_providers=[]):
        self.track_name_to_data_track = OrderedDict()
        self.attribute_name_to_attribute_provider = OrderedDict()
        for data_track in data_tracks:
            self.add_track(data_track)
        for attribute_provider in attribute_providers:
            self.attribute_name_to_attribute_provider[attribute_provider.name]\
                = attribute_provider 

    def add_track(self, data_track):
        assert type(data_track).__name__=="DataTrack"
        if len(self.track_name_to_data_track)==0:
            self.num_items = len(data_track) 
        else:
            assert len(data_track)==self.num_items,\
                    ("first track had "+str(self.num_items)+" but "
                     "data track has "+str(len(data_track))+" items")
        self.track_name_to_data_track[data_track.name] = data_track
        return self

    def create_seqlets(self, coords, track_names=None, attribute_names=None):
        seqlets = []
        for coor in coords:
            seqlets.append(self.create_seqlet(coor=coor,
                                              track_names=track_names,
                                              attribute_names=attribute_names))
        return seqlets

    def create_seqlet(self, coor, track_names=None, attribute_names=None):
        if (track_names is None):
            track_names=self.track_name_to_data_track.keys()
        if (attribute_names is None):
            attribute_names=self.attribute_name_to_attribute_provider.keys()
        seqlet = Seqlet(coor=coor)
        self.augment_seqlet(seqlet=seqlet, track_names=track_names,
                            attribute_names=attribute_names) 
        return seqlet

    def augment_seqlet(self, seqlet, track_names, attribute_names):
        for track_name in track_names:
            seqlet.add_snippet_from_data_track(
                data_track=self.track_name_to_data_track[track_name])
        for attribute_name in attribute_names:
            seqlet.set_attribute(
                attribute_provider=\
                 self.attribute_name_to_attribute_provider[attribute_name])
        return seqlet

    @property
    def track_length(self):
        return self.track_name_to_data_track.values()[0].track_length


class CoordOverlapDetector(object):

    def __init__(self, min_overlap_fraction):
        self.min_overlap_fraction = min_overlap_fraction

    def __call__(self, coord1, coord2):
        if (coord1.example_idx != coord2.example_idx):
            return False
        min_overlap = self.min_overlap_fraction*min(len(coord1), len(coord2))
        overlap_amt = (min(coord1.end, coord2.end)-
                       max(coord1.start, coord2.start))
        return (overlap_amt >= min_overlap)


class SeqletComparator(object):

    def __init__(self, value_provider):
        self.value_provider = value_provider

    def get_larger(self, seqlet1, seqlet2):
        return (seqlet1 if (self.value_provider(seqlet1) >=
                            self.value_provider(seqlet2)) else seqlet2)

    def get_smaller(self, seqlet1, seqlet2):
        return (seqlet1 if (self.value_provider(seqlet1) <=
                            self.value_provider(seqlet2)) else seqlet2)


class SeqletsOverlapResolver(object):

    def __init__(self, overlap_detector,
                       seqlet_comparator):
        self.overlap_detector = overlap_detector
        self.seqlet_comparator = seqlet_comparator

    def __call__(self, all_seqlets):
        example_idx_to_seqlets = defaultdict(list)  
        for seqlet in all_seqlets:
            example_idx_to_seqlets[seqlet.coor.example_idx].append(seqlet)
        for example_idx, seqlets in example_idx_to_seqlets.items():
            final_seqlets_set = set(seqlets)
            for i in range(len(seqlets)):
                seqlet1 = seqlets[i]
                for seqlet2 in seqlets[i+1:]:
                    if (seqlet1 not in final_seqlets_set):
                        break
                    if ((seqlet2 in final_seqlets_set)
                         and self.overlap_detector(seqlet1.coor, seqlet2.coor)):
                        final_seqlets_set.remove(
                         self.seqlet_comparator.get_smaller(seqlet1, seqlet2)) 
            example_idx_to_seqlets[example_idx] = list(final_seqlets_set)
        return list(itertools.chain(*example_idx_to_seqlets.values())) 


class AbstractAttributeProvider(object):

    def __init__(self, name):
        self.name = name

    def annotate(self, seqlets):
        for seqlet in seqlets:
            seqlet.set_attribute(self)

    def __call__(self, seqlet):
        raise NotImplementedError()


class AbstractLabeler(AbstractAttributeProvider):

    def __init__(self, name):
        super(AbstractLabeler, self).__init__(name=name)

    def fit(self, seqlets):
        raise NotImplementedError()

    def __call__(self, seqlet): #provide the label
        raise NotImplementedError()


class AbstractThresholdLabeler(AbstractLabeler):

    def __init__(self, name):
        super(AbstractThresholdLabeler, self).__init__(name=name)
        self.threshold = None

    def get_val(self, seqlet):
        raise NotImplementedError()

    def determine_threshold_from_vals(self, vals):
        raise NotImplementedError()

    def get_label_given_threshold_and_val(self, threshold, val):
        raise NotImplementedError()

    def fit(self, seqlets):
        self.threshold = self.determine_threshold_from_vals(
                            [self.get_val(x) for x in seqlets])

    def __call__(self, seqlet):
        if (self.threshold is None):
            raise RuntimeError("Set threshold by calling fit()")
        return self.get_label_given_threshold_and_val(
                    threshold=self.threshold,
                    val=self.get_val(seqlet))


class SignedContribThresholdLabeler(AbstractThresholdLabeler):

    def __init__(self, name, track_name, flank_to_ignore):
        super(SignedContribThresholdLabeler, self).__init__(name=name)
        self.track_name = track_name
        self.flank_to_ignore = flank_to_ignore

    def get_val(self, seqlet):
        track_values = seqlet[self.track_name]\
                        .fwd[self.flank_to_ignore:-self.flank_to_ignore]
        return np.sum(track_values)

    def determine_threshold_from_vals(self, vals):
        return np.min(np.abs(vals))

    def get_label_given_threshold_and_val(self, threshold, val):
       # sigmoid_logit = (np.abs(val)/threshold - 1.0)/100.0
       # sigmoid_logit = min(sigmoid_logit, 10.0)
       # return (np.exp(sigmoid_logit)/(1+np.exp(sigmoid_logit)))*np.sign(val)
       # sigmoid_logit = np.abs(val)*(15.0/threshold)
       # sigmoid_logit = min(sigmoid_logit, 15)
        core_val = np.abs(val)/threshold
        core_val = ((1+(np.log(core_val)/np.log(2)))
                    if (core_val >= 1) else core_val)
        return core_val*np.sign(val)
       # return (2*(np.exp(sigmoid_logit)/                                      
       #             (1+np.exp(sigmoid_logit)))-1)*np.sign(val)
        #return (threshold <= np.abs(val))*np.sign(val)


class MultiTaskSeqletCreation(object):

    def __init__(self, coord_producer,
                       track_set,
                       overlap_resolver, verbose=True):
        self.coord_producer = coord_producer
        self.track_set = track_set
        self.overlap_resolver = overlap_resolver
        self.verbose=verbose

    def __call__(self, task_name_to_score_track,
                       task_name_to_labeler):
        task_name_to_seqlets = {}
        for task_name in task_name_to_score_track:
            print("On task",task_name)
            score_track = task_name_to_score_track[task_name]
            seqlets = self.track_set.create_seqlets(
                        coords=self.coord_producer(score_track=score_track)) 
            task_name_to_labeler[task_name].fit(seqlets)
            task_name_to_seqlets[task_name] = seqlets
        final_seqlets = self.overlap_resolver(
            itertools.chain(*task_name_to_seqlets.values()))
        if (self.verbose):
            print("After resolving overlaps, got "
                  +str(len(final_seqlets))+" seqlets")
        for labeler in task_name_to_labeler.values():
            labeler.annotate(final_seqlets)
        return final_seqlets 

            
class SeqletCoordinates(object):

    def __init__(self, example_idx, start, end, is_revcomp):
        self.example_idx = example_idx
        self.start = start
        self.end = end
        self.is_revcomp = is_revcomp

    def revcomp(self):
        return SeqletCoordinates(
                example_idx=self.example_idx,
                start=self.start, end=self.end,
                is_revcomp=(self.is_revcomp==False))

    def __len__(self):
        return self.end - self.start

    def __str__(self):
        return ("example:"+str(self.example_idx)
                +",loc:"+str(self.start)+",end:"+str(self.end)
                +",rc:"+str(self.is_revcomp))


class Pattern(object):

    def __init__(self):
        self.track_name_to_snippet = OrderedDict()
        self.attribute_name_to_attribute = OrderedDict()

    def __getitem__(self, key):
        if (key in self.track_name_to_snippet):
            return self.track_name_to_snippet[key]
        elif (key in self.attribute_name_to_attribute):
            return self.attribute_name_to_attribute[key]
        else:
            raise RuntimeError("No key "+str(key)+"; snippet keys are: "
                +str(self.track_name_to_snippet.keys())+" and "
                +" attribute keys are "
                +str(self.attribute_name_to_attribute.keys()))

    def __setitem__(self, key, value):
        assert key not in self.track_name_to_snippet,\
            "Don't use setitem to set keys that are in track_name_to_snippet;"\
            +" use add_snippet_from_data_track"
        self.attribute_name_to_attribute[key] = value

    def set_attribute(self, attribute_provider):
        self[attribute_provider.name] = attribute_provider(self)

    def __len__(self):
        raise NotImplementedError()

    def revcomp(self):
        raise NotImplementedError()


class Seqlet(Pattern):

    def __init__(self, coor):
        self.coor = coor
        super(Seqlet, self).__init__()

    def add_snippet_from_data_track(self, data_track): 
        snippet = data_track.get_snippet(coor=self.coor)
        return self.add_snippet(data_track_name=data_track.name,
                                snippet=snippet)

    def add_snippet(self, data_track_name, snippet):
        if (snippet.has_pos_axis):
            assert len(snippet)==len(self),\
                   ("tried to add snippet with pos axis of len "
                    +str(len(snippet))+" but snippet coords have "
                    +"len "+str(self.coor))
        self.track_name_to_snippet[data_track_name] = snippet 
        return self

    def add_attribute(self, attribute_name, attribute):
        self.attribute_name_to_attribute[attribute_name] = attribute

    def revcomp(self):
        seqlet = Seqlet(coor=self.coor.revcomp())
        for track_name in self.track_name_to_snippet:
            seqlet.add_snippet(
                data_track_name=track_name,
                snippet=self.track_name_to_snippet[track_name].revcomp()) 
        for attribute_name in self.attribute_name_to_attribute:
            seqlet.add_attribute(
                attribute_name=attribute_name,
                attribute=self.attribute_name_to_attribute[attribute_name])
        return seqlet

    def trim(self, start_idx, end_idx):
        if (self.coor.is_revcomp == False):
            new_coor_start = self.coor.start+start_idx 
            new_coor_end = self.coor.start+end_idx
        else:
            new_coor_start = self.coor.start + (len(self)-end_idx)
            new_coor_end = self.coor.end-start_idx
        new_coor = SeqletCoordinates(
                    start=new_coor_start,
                    end=new_coor_end,
                    example_idx=self.coor.example_idx,
                    is_revcomp=self.coor.is_revcomp) 
        new_seqlet = Seqlet(coor=new_coor)  
        for data_track_name in self.track_name_to_snippet:
            new_seqlet.add_snippet(
                data_track_name=data_track_name,
                snippet=self[data_track_name].trim(start_idx, end_idx))
        return new_seqlet

    def __len__(self):
        return len(self.coor)

    @property
    def exidx_start_end_string(self):
        return (str(self.coor.example_idx)+"_"
                +str(self.coor.start)+"_"+str(self.coor.end))
 
        
class SeqletAndAlignment(object):

    def __init__(self, seqlet, alnmt):
        self.seqlet = seqlet
        #alnmt is the position of the beginning of seqlet
        #in the aggregated seqlet
        self.alnmt = alnmt 


class AbstractPatternAligner(object):

    def __init__(self, track_names, normalizer):
        self.track_names = track_names
        self.normalizer = normalizer

    def __call__(self, parent_pattern, child_pattern):
        #return an alignment
        raise NotImplementedError()


class CrossMetricPatternAligner(AbstractPatternAligner):

    def __init__(self, pattern_comparison_settings, metric):
        self.pattern_comparison_settings = pattern_comparison_settings 
        self.metric = metric

    def __call__(self, parent_pattern, child_pattern):
        fwd_data_parent, rev_data_parent = get_2d_data_from_pattern(
            pattern=parent_pattern,
            track_names=self.pattern_comparison_settings.track_names,
            track_transformer=
             self.pattern_comparison_settings.track_transformer) 
        fwd_data_child, rev_data_child = get_2d_data_from_pattern(
            pattern=child_pattern,
            track_names=self.pattern_comparison_settings.track_names,
            track_transformer=
             self.pattern_comparison_settings.track_transformer) 
        #find optimal alignments of fwd_data_child and rev_data_child
        #with fwd_data_parent.
        best_crossmetric, best_crossmetric_argmax =\
            self.metric(
                parent_matrix=fwd_data_parent,
                child_matrix=fwd_data_child,
                min_overlap=self.pattern_comparison_settings.min_overlap)  
        best_crossmetric_rev, best_crossmetric_argmax_rev =\
            self.metric(
                parent_matrix=fwd_data_parent,
                child_matrix=rev_data_child,
                min_overlap=self.pattern_comparison_settings.min_overlap) 
        if (best_crossmetric_rev > best_crossmetric):
            return (best_crossmetric_argmax_rev, True, best_crossmetric_rev)
        else:
            return (best_crossmetric_argmax, False, best_crossmetric)


class CrossCorrelationPatternAligner(CrossMetricPatternAligner):

    def __init__(self, pattern_comparison_settings):
        super(CrossCorrelationPatternAligner, self).__init__(
            pattern_comparison_settings=pattern_comparison_settings,
            metric=get_best_alignment_crosscorr)


class CrossContinJaccardPatternAligner(CrossMetricPatternAligner):

    def __init__(self, pattern_comparison_settings):
        super(CrossContinJaccardPatternAligner, self).__init__(
            pattern_comparison_settings=pattern_comparison_settings,
            metric=get_best_alignment_crosscontinjaccard)


#implements the array interface but also tracks the
#unique seqlets for quick membership testing
class SeqletsAndAlignments(object):

    def __init__(self):
        self.arr = []
        self.unique_seqlets = {} 

    def __len__(self):
        return len(self.arr)

    def __iter__(self):
        return self.arr.__iter__()

    def __getitem__(self, idx):
        return self.arr[idx]

    def __contains__(self, seqlet):
        return (seqlet.exidx_start_end_string in self.unique_seqlets)

    def append(self, seqlet_and_alnmt):
        seqlet = seqlet_and_alnmt.seqlet
        if (seqlet.exidx_start_end_string in self.unique_seqlets):
            raise RuntimeError("Seqlet "
             +seqlet.exidx_start_end_string
             +" is already in SeqletsAndAlignments array")
        self.arr.append(seqlet_and_alnmt)
        self.unique_seqlets[seqlet.exidx_start_end_string] = seqlet

    def get_seqlets(self):
        return [x.seqlet for x in self.arr]

    def save_hdf5(self, grp):
        util.save_seqlet_coords(seqlets=self.seqlets,
                                dset_name="seqlets", grp=grp) 
        grp.create_dataset("alnmts",
                           data=np.array([x.alnmt for x in self.arr]))

    def copy(self):
        the_copy = SeqletsAndAlignments()
        for seqlet_and_alnmt in self:
            the_copy.append(seqlet_and_alnmt)
        return the_copy


class AggregatedSeqlet(Pattern):

    def __init__(self, seqlets_and_alnmts_arr):
        super(AggregatedSeqlet, self).__init__()
        self._seqlets_and_alnmts = SeqletsAndAlignments()
        if (len(seqlets_and_alnmts_arr)>0):
            #make sure the start is 0
            start_idx = min([x.alnmt for x in seqlets_and_alnmts_arr])
            seqlets_and_alnmts_arr = [SeqletAndAlignment(seqlet=x.seqlet,
                alnmt=x.alnmt-start_idx) for x in seqlets_and_alnmts_arr] 
            self._set_length(seqlets_and_alnmts_arr)
            self._compute_aggregation(seqlets_and_alnmts_arr) 

    def save_hdf5(self, grp):
        for track_name,snippet in self.track_name_to_snippet.items():
            snippet.save_hdf5(grp.create_group(track_name))
        self._seqlets_and_alnmts.save_hdf5(
             grp.create_group("seqlets_and_alnmts"))
        

    def copy(self):
        return AggregatedSeqlet(seqlets_and_alnmts_arr=
                                self._seqlets_and_alnmts.copy())

    def get_fwd_seqlet_data(self, track_names, track_transformer):
        to_return = []
        for seqlet in [x.seqlet for x in self._seqlets_and_alnmts]:
            to_return.append(get_2d_data_from_pattern(pattern=seqlet,
                                track_names=track_names, 
                                track_transformer=track_transformer)[0])
        return np.array(to_return) 

    def trim_to_positions_with_frac_support_of_peak(self, frac):
        per_position_center_counts =\
            self.get_per_position_seqlet_center_counts()
        max_support = max(per_position_center_counts)
        left_idx = 0
        while per_position_center_counts[left_idx] < frac*max_support:
            left_idx += 1
        right_idx = len(per_position_center_counts)
        while per_position_center_counts[right_idx-1] < frac*max_support:
            right_idx -= 1

        retained_seqlets_and_alnmts = []
        for seqlet_and_alnmt in self.seqlets_and_alnmts:
            seqlet_center = (
                seqlet_and_alnmt.alnmt+0.5*len(seqlet_and_alnmt.seqlet))
            #if the seqlet will fit within the trimmed pattern
            if ((seqlet_center >= left_idx) and
                (seqlet_center <= right_idx)):
                retained_seqlets_and_alnmts.append(seqlet_and_alnmt)
        new_start_idx = min([x.alnmt for x in retained_seqlets_and_alnmts])
        new_seqlets_and_alnmnts = [SeqletAndAlignment(seqlet=x.seqlet,
                                    alnmt=x.alnmt-new_start_idx) for x in
                                    retained_seqlets_and_alnmts] 
        return AggregatedSeqlet(seqlets_and_alnmts_arr=new_seqlets_and_alnmnts) 

    def trim_to_start_and_end_idx(self, start_idx, end_idx):
        new_seqlets_and_alnmnts = [] 
        for seqlet_and_alnmt in self._seqlets_and_alnmts:
            if (seqlet_and_alnmt.alnmt < end_idx and
                ((seqlet_and_alnmt.alnmt + len(seqlet_and_alnmt.seqlet))
                  > start_idx)):
                if seqlet_and_alnmt.alnmt > start_idx:
                    seqlet_start_idx_trim = 0 
                    new_alnmt = seqlet_and_alnmt.alnmt-start_idx
                else:
                    seqlet_start_idx_trim = start_idx - seqlet_and_alnmt.alnmt 
                    new_alnmt = 0
                if (seqlet_and_alnmt.alnmt+len(seqlet_and_alnmt.seqlet)
                    < end_idx):
                    seqlet_end_idx_trim = len(seqlet_and_alnmt.seqlet)
                else:
                    seqlet_end_idx_trim = end_idx - seqlet_and_alnmt.alnmt
                new_seqlet = seqlet_and_alnmt.seqlet.trim(
                                start_idx=seqlet_start_idx_trim,
                                end_idx=seqlet_end_idx_trim)
                new_seqlets_and_alnmnts.append(
                    SeqletAndAlignment(seqlet=new_seqlet,
                                       alnmt=new_alnmt)) 
            else:
                print(seqlet_and_alnmt.alnmt)
                print(len(seqlet_and_alnmt.seqlet))
                print(start_idx, end_idx)
                assert False
        return AggregatedSeqlet(seqlets_and_alnmts_arr=new_seqlets_and_alnmnts)

    def get_per_position_seqlet_center_counts(self):
        per_position_center_counts = np.zeros(len(self.per_position_counts))
        for seqlet_and_alnmt in self._seqlets_and_alnmts:
            center = seqlet_and_alnmt.alnmt +\
                      int(len(seqlet_and_alnmt.seqlet)*0.5)
            per_position_center_counts[center] += 1
        return per_position_center_counts

    def plot_counts(self, counts, figsize=(20,2)):
        from matplotlib import pyplot as plt
        fig = plt.figure(figsize=figsize)
        ax = fig.add_subplot(111)
        self.plot_counts_given_ax(ax=ax, counts=counts)
        plt.show()

    def plot_counts_given_ax(self, ax, counts):
        ax.plot(counts)
        ax.set_ylim((0,max(counts)*1.1))
        ax.set_xlim((0, len(self)))

    def _set_length(self, seqlets_and_alnmts_arr):
        self.length = max([x.alnmt + len(x.seqlet)
                       for x in seqlets_and_alnmts_arr])  

    @property
    def seqlets_and_alnmts(self):
        return self._seqlets_and_alnmts

    @property
    def seqlets(self):
        return self._seqlets_and_alnmts.get_seqlets()

    @seqlets_and_alnmts.setter
    def seqlets_and_alnmts(self, val):
        assert type(val).__name__ == "SeqletsAndAlignments"
        self._seqlets_and_alnmts = val

    @property
    def num_seqlets(self):
        return len(self.seqlets_and_alnmts)

    @staticmethod 
    def from_seqlet(seqlet):
        return AggregatedSeqlet(seqlets_and_alnmts_arr=
                                [SeqletAndAlignment(seqlet,0)])

    def _compute_aggregation(self,seqlets_and_alnmts_arr):
        self._initialize_track_name_to_aggregation(
              sample_seqlet=seqlets_and_alnmts_arr[0].seqlet)
        self.per_position_counts = np.zeros((self.length,))
        for seqlet_and_alnmt in seqlets_and_alnmts_arr:
            if (seqlet_and_alnmt.seqlet not in self.seqlets_and_alnmts): 
                self._add_pattern_with_valid_alnmt(
                        pattern=seqlet_and_alnmt.seqlet,
                        alnmt=seqlet_and_alnmt.alnmt)

    def _initialize_track_name_to_aggregation(self, sample_seqlet): 
        self._track_name_to_agg = OrderedDict() 
        self._track_name_to_agg_revcomp = OrderedDict() 
        for track_name in sample_seqlet.track_name_to_snippet:
            track_shape = tuple([self.length]
                           +list(sample_seqlet[track_name].fwd.shape[1:]))
            self._track_name_to_agg[track_name] =\
                np.zeros(track_shape).astype("float") 
            self._track_name_to_agg_revcomp[track_name] =\
                np.zeros(track_shape).astype("float") 
            self.track_name_to_snippet[track_name] = Snippet(
                fwd=self._track_name_to_agg[track_name],
                rev=self._track_name_to_agg_revcomp[track_name],
                has_pos_axis=sample_seqlet[track_name].has_pos_axis) 

    def get_nonzero_average(self, track_name, pseudocount):
        fwd_nonzero_count = np.zeros_like(self[track_name].fwd)
        rev_nonzero_count = np.zeros_like(self[track_name].rev)
        has_pos_axis = self[track_name].has_pos_axis
        for seqlet_and_alnmt in self.seqlets_and_alnmts:
            alnmt = seqlet_and_alnmt.alnmt
            seqlet_length = len(seqlet_and_alnmt.seqlet)
            motif_length = len(rev_nonzero_count)
            fwd_nonzero_count[alnmt:(alnmt+seqlet_length)] +=\
                (np.abs(seqlet_and_alnmt.seqlet[track_name].fwd) > 0.0)
            rev_nonzero_count[motif_length-(alnmt+seqlet_length):
                              motif_length-alnmt] +=\
                (np.abs(seqlet_and_alnmt.seqlet[track_name].rev) > 0.0)
        return Snippet(fwd=self._track_name_to_agg[track_name]
                           /(fwd_nonzero_count+pseudocount),
                       rev=self._track_name_to_agg_revcomp[track_name]
                           /(rev_nonzero_count+pseudocount),
                       has_pos_axis=has_pos_axis)


    def _pad_before(self, num_zeros):
        assert num_zeros > 0
        self.length += num_zeros
        for seqlet_and_alnmt in self.seqlets_and_alnmts:
            seqlet_and_alnmt.alnmt += num_zeros
        self.per_position_counts =\
            np.concatenate([np.zeros((num_zeros,)),
                            self.per_position_counts],axis=0) 
        for track_name in self.track_name_to_snippet:
            track = self._track_name_to_agg[track_name]
            if (self.track_name_to_snippet[track_name].has_pos_axis):
                rev_track = self._track_name_to_agg_revcomp[track_name]
                padding_shape = tuple([num_zeros]+list(track.shape[1:])) 
                extended_track = np.concatenate(
                    [np.zeros(padding_shape), track], axis=0)
                extended_rev_track = np.concatenate(
                    [rev_track, np.zeros(padding_shape)], axis=0)
                self._track_name_to_agg[track_name] = extended_track
                self._track_name_to_agg_revcomp[track_name] =\
                    extended_rev_track

    def _pad_after(self, num_zeros):
        assert num_zeros > 0
        self.length += num_zeros 
        self.per_position_counts =\
            np.concatenate([self.per_position_counts,
                            np.zeros((num_zeros,))],axis=0) 
        for track_name in self.track_name_to_snippet:
            track = self._track_name_to_agg[track_name]
            if (self.track_name_to_snippet[track_name].has_pos_axis):
                rev_track = self._track_name_to_agg_revcomp[track_name]
                padding_shape = tuple([num_zeros]+list(track.shape[1:])) 
                extended_track = np.concatenate(
                    [track, np.zeros(padding_shape)], axis=0)
                extended_rev_track = np.concatenate(
                    [np.zeros(padding_shape),rev_track], axis=0)
                self._track_name_to_agg[track_name] = extended_track
                self._track_name_to_agg_revcomp[track_name] =\
                    extended_rev_track

    def merge_aggregated_seqlet(self, agg_seqlet, aligner):
        self.merge_seqlets_and_alnmts(
            seqlets_and_alnmts=agg_seqlet.seqlets_and_alnmts,
            aligner=aligner)

    def merge_seqlets_and_alnmts(self, seqlets_and_alnmts, aligner):
        for seqlet_and_alnmt in seqlets_and_alnmts:
            #only merge those seqlets in agg_seqlet that are not already
            #in the current seqlet
            if (seqlet_and_alnmt.seqlet not in self.seqlets_and_alnmts): 
                self.add_pattern(pattern=seqlet_and_alnmt.seqlet,
                                 aligner=aligner) 
        
    def add_pattern(self, pattern, aligner):
        (alnmt, revcomp_match, alnmt_score) =\
            aligner(parent_pattern=self, child_pattern=pattern)
        if (revcomp_match):
            pattern = pattern.revcomp()
        if alnmt < 0:
           self._pad_before(num_zeros=abs(alnmt)) 
           alnmt=0
        end_coor_of_pattern = (alnmt + len(pattern))
        if (end_coor_of_pattern > self.length):
            self._pad_after(num_zeros=(end_coor_of_pattern - self.length))
        self._add_pattern_with_valid_alnmt(pattern=pattern, alnmt=alnmt)

    def _add_pattern_with_valid_alnmt(self, pattern, alnmt):
        assert alnmt >= 0
        assert alnmt + len(pattern) <= self.length

        slice_obj = slice(alnmt, alnmt+len(pattern))
        rev_slice_obj = slice(self.length-(alnmt+len(pattern)),
                              self.length-alnmt)

        self.seqlets_and_alnmts.append(
             SeqletAndAlignment(seqlet=pattern, alnmt=alnmt))
        self.per_position_counts[slice_obj] += 1.0 

        for track_name in self._track_name_to_agg:
            if (self.track_name_to_snippet[track_name].has_pos_axis==False):
                self._track_name_to_agg[track_name] +=\
                    pattern[track_name].fwd
                self._track_name_to_agg_revcomp[track_name] +=\
                    pattern[track_name].rev
            else:
                self._track_name_to_agg[track_name][slice_obj] +=\
                    pattern[track_name].fwd 
                self._track_name_to_agg_revcomp[track_name][rev_slice_obj]\
                     += pattern[track_name].rev
            self.track_name_to_snippet[track_name] =\
             Snippet(
              fwd=(self._track_name_to_agg[track_name]
                   /self.per_position_counts[:,None]),
              rev=(self._track_name_to_agg_revcomp[track_name]
                   /self.per_position_counts[::-1,None]),
              has_pos_axis=self.track_name_to_snippet[track_name].has_pos_axis) 

    def __len__(self):
        return self.length

    def revcomp(self):
        rev_agg_seqlet = AggregatedSeqlet(seqlets_and_alnmts_arr=[])
        rev_agg_seqlet.per_position_counts = self.per_position_counts[::-1]
        rev_agg_seqlet._track_name_to_agg = OrderedDict(
         [(x, np.copy(self._track_name_to_agg_revcomp[x]))
           for x in self._track_name_to_agg])
        rev_agg_seqlet._track_name_to_agg_revcomp = OrderedDict(
         [(x, np.copy(self._track_name_to_agg[x]))
           for x in self._track_name_to_agg_revcomp])
        rev_agg_seqlet.track_name_to_snippet = OrderedDict([
         (x, Snippet(
             fwd=np.copy(self.track_name_to_snippet[x].rev),
             rev=np.copy(self.track_name_to_snippet[x].fwd),
             has_pos_axis=self.track_name_to_snippet[x].has_pos_axis)) 
         for x in self.track_name_to_snippet]) 
        rev_seqlets_and_alignments_arr = [
            SeqletAndAlignment(seqlet=x.seqlet.revcomp(),
                               alnmt=self.length-(x.alnmt+len(x.seqlet)))
            for x in self.seqlets_and_alnmts] 
        rev_agg_seqlet._set_length(rev_seqlets_and_alignments_arr)
        for seqlet_and_alnmt in rev_seqlets_and_alignments_arr:
            rev_agg_seqlet.seqlets_and_alnmts.append(seqlet_and_alnmt)
        return rev_agg_seqlet 

    def get_seqlet_coor_centers(self):
        return [x.seqlet.coor.start + 0.5*(len(x.seqlet))
                for x in self.seqlets_and_alnmts] 

    def viz_positional_distribution(self, bins=None):
        from matplotlib import pyplot as plt
        plt.hist(self.get_seqlet_coor_centers(), bins=bins)
        plt.show()


def get_1d_data_from_patterns(patterns, attribute_names):
    to_return = []
    for pattern in patterns:
        to_return.append([pattern[attribute_name] for attribute_name
                          in attribute_names])
    return np.array(to_return)


def get_2d_data_from_patterns(patterns, track_names, track_transformer):
    all_fwd_data = []
    all_rev_data = []
    for pattern in patterns:
        fwd_data, rev_data = get_2d_data_from_pattern(
            pattern=pattern, track_names=track_names,
            track_transformer=track_transformer) 
        all_fwd_data.append(fwd_data)
        all_rev_data.append(rev_data)
    return (np.array(all_fwd_data),
            np.array(all_rev_data))


def get_2d_data_from_pattern(pattern, track_names, track_transformer): 
    snippets = [pattern[track_name]
                 for track_name in track_names] 
    if (track_transformer is None):
        track_transformer = lambda x: x
    fwd_data = np.concatenate([track_transformer(
             np.reshape(snippet.fwd, (len(snippet.fwd), -1)))
            for snippet in snippets], axis=1)
    rev_data = np.concatenate([track_transformer(
            np.reshape(snippet.rev, (len(snippet.rev), -1)))
            for snippet in snippets], axis=1)
    return fwd_data, rev_data


def get_best_alignment_crossmetric(parent_matrix, child_matrix,
                                   min_overlap, metric):
    assert len(np.shape(parent_matrix))==2
    assert len(np.shape(child_matrix))==2
    assert np.shape(parent_matrix)[1] == np.shape(child_matrix)[1]

    padding_amt = int(np.ceil(np.shape(child_matrix)[0]*(1-min_overlap)))
    #pad the parent matrix as necessary
    parent_matrix = np.pad(array=parent_matrix,
                           pad_width=[(padding_amt, padding_amt),(0,0)],
                           mode='constant')
    correlations = metric(
        in1=parent_matrix, in2=child_matrix)
    best_crosscorr_argmax = np.argmax(correlations)-padding_amt
    best_crosscorr = np.max(correlations)
    return (best_crosscorr, best_crosscorr_argmax)


def get_best_alignment_crosscorr(parent_matrix, child_matrix, min_overlap):
    return get_best_alignment_crossmetric(
                parent_matrix=parent_matrix, child_matrix=child_matrix,
                min_overlap=min_overlap,
                metric=(lambda in1,in2: scipy.signal.correlate2d(
                                         in1=in1, in2=in2, mode='valid')))


def get_best_alignment_crossabsdiff(parent_matrix, child_matrix, min_overlap):
    return get_best_alignment_crossmetric(
                parent_matrix=parent_matrix, child_matrix=child_matrix,
                min_overlap=min_overlap,
                metric=(lambda in1,in2: cross_absdiff(in1=in1, in2=in2)))


def get_best_alignment_crosscontinjaccard(
        parent_matrix, child_matrix, min_overlap):
    return get_best_alignment_crossmetric(
                parent_matrix=parent_matrix, child_matrix=child_matrix,
                min_overlap=min_overlap,
                metric=(lambda in1,in2: cross_continjaccard(in1=in1, in2=in2)))


def cross_absdiff(in1, in2):
    assert len(in1.shape)==2
    assert len(in2.shape)==2
    assert in1.shape[1] == in2.shape[1]
    len_result = (1+len(in1)-len(in2))
    to_return = np.zeros(len_result)
    for idx in range(len_result):
        snippet = in1[idx:idx+in2.shape[0]]
        to_return[idx] = np.sum(np.abs(snippet-in2),axis=(1,2))
    return to_return


def cross_continjaccard(in1, in2):
    len_result = (1+len(in1)-len(in2))
    to_return = np.zeros(len_result)
    for idx in range(len_result):
        snippet = in1[idx:idx+in2.shape[0]]
        to_return[idx] = continjaccard(in1=snippet, in2=in2)
    return to_return


def continjaccard(in1, in2):
    assert len(in1.shape)==2
    assert len(in2.shape)==2
    assert in1.shape[1] == in2.shape[1]
    union = np.sum(np.maximum(np.abs(in1),np.abs(in2)))
    intersection = np.minimum(np.abs(in1),np.abs(in2))
    signs = np.sign(in1)*np.sign(in2)
    return np.sum(signs*intersection)/union


def corr(in1, in2):
    assert len(in1.shape)==2
    assert len(in2.shape)==2
    assert in1.shape[1] == in2.shape[1]
    return np.dot((in1/np.linalg.norm(in1)).ravel(),
                  (in2/np.linalg.norm(in2)).ravel()) 


def neg_max_kl_div(in1, in2):
    assert len(in1.shape)==2
    assert len(in2.shape)==2
    assert in1.shape[1] == in2.shape[1]
    assert np.max(np.abs(np.sum(in1, axis=1)-1.0)) < 0.00001
    #pseudocount
    in1 = (in1+0.0001)/1.0004
    in2 = (in2+0.0001)/1.0004
    kldiv1 = np.sum(in1*np.log(in1/in2),axis=1) 
    kldiv2 = np.sum(in2*np.log(in2/in1),axis=1) 
    return -np.max(0.5*(kldiv1+kldiv2))
