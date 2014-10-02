#! /usr/bin/env python

##############################################################################
##  DendroPy Phylogenetic Computing Library.
##
##  Copyright 2010-2014 Jeet Sukumaran and Mark T. Holder.
##  All rights reserved.
##
##  See "LICENSE.txt" for terms and conditions of usage.
##
##  If you use this work or any portion thereof in published work,
##  please cite it as:
##
##     Sukumaran, J. and M. T. Holder. 2010. DendroPy: a Python library
##     for phylogenetic computing. Bioinformatics 26: 1569-1571.
##
##############################################################################

"""
Split calculation and management.
"""

import sys
from copy import deepcopy
import math
from dendropy.utility import container
from dendropy.utility import textprocessing
from dendropy.utility import deprecate
from dendropy.mathlib import statistics

import dendropy

##############################################################################
## Build tree from splits

def tree_from_splits(
        splits,
        taxon_namespace,
        split_edge_lengths=None,
        is_rooted=False):
    """
    Builds a tree from a set of splits, `splits`, using taxon references from
    `taxon_namespace`.
    If `is_rooted` is True, then tree will be rooted.
    If `split_edge_lengths` is not None, it should be a dictionary mapping
    splits to edge lengths.
    """
    leaf_to_root_search = True
    con_tree = dendropy.Tree(taxon_namespace=taxon_namespace)
    con_tree.is_rooted = is_rooted
    for taxon in taxon_namespace:
        con_tree.seed_node.new_child(taxon=taxon)
    taxa_mask = taxon_namespace.all_taxa_bitmask()
    encode_splits(con_tree)
    leaves = con_tree.leaf_nodes()

    if leaf_to_root_search:
        to_leaf_dict = {}
        for leaf in leaves:
            to_leaf_dict[leaf.edge.split_bitmask] = leaf

    root = con_tree.seed_node
    root_edge = root.edge

    splits_to_add = []
    #new_old_split_map = {}
    for s in splits:
        m = s & taxa_mask
        if (m != taxa_mask) and ((m-1) & m): # if not root (i.e., all "1's") and not singleton (i.e., one "1")
            if not is_rooted:
                c = (~m) & taxa_mask
                if (c-1) & c: # not singleton (i.e., one "0")
                    if 1 & m:
                        k = c
                    else:
                        k = m
                    splits_to_add.append(k)
                    #new_old_split_map[k] = m
            else:
                splits_to_add.append(m)
                #new_old_split_map[m] = m

    # Now when we add splits in order, we will do a greedy, extended majority-rule consensus tree
    #for freq, split_to_add, split_in_dict in to_try_to_add:
    for split_to_add in splits_to_add:
        if (split_to_add & root_edge.split_bitmask) != split_to_add:
            continue
        elif leaf_to_root_search:
            lb = lowest_bit_only(split_to_add)
            one_leaf = to_leaf_dict[lb]
            parent_node = one_leaf
            while (split_to_add & parent_node.edge.split_bitmask) != split_to_add:
                parent_node = parent_node.parent_node
        else:
            parent_node = con_tree.mrca(split_bitmask=split_to_add)
        if parent_node is None or parent_node.edge.split_bitmask == split_to_add:
            continue # split is not in tree, or already in tree.
        new_node = dendropy.Node()
        #self.map_split_support_to_node(node=new_node, split_support=freq)
        new_node_children = []
        new_edge = new_node.edge
        new_edge.split_bitmask = 0
        for child in parent_node.child_nodes():
            # might need to modify the following if rooted splits
            # are used
            cecm = child.edge.split_bitmask
            if (cecm & split_to_add ):
                assert cecm != split_to_add
                new_edge.split_bitmask |= cecm
                new_node_children.append(child)

        # Check to see if we have accumulated all of the bits that we
        #   needed, but none that we don't need.
        if new_edge.split_bitmask == split_to_add:
            if split_edge_lengths:
                new_edge.length = split_edge_lengths[split_to_add]
                #old_split = new_old_split_map[split_to_add]
                #new_edge.length = split_edge_lengths[old_split]
            for child in new_node_children:
                parent_node.remove_child(child)
                new_node.add_child(child)
            parent_node.add_child(new_node)
            con_tree.split_edge_map[split_to_add] = new_edge
    return con_tree

###############################################################################
## TOOLS/UTILITIES FOR MANAGING SPLITS

def split_to_list(s, mask=-1, one_based=False, ordination_in_mask=False):
    return [i for i in iter_split_indices(s, mask, one_based, ordination_in_mask)]

def iter_split_indices(s, mask=-1, one_based=False, ordination_in_mask=False):
    '''returns the index of each bit that is on in `s` and the `mask`

        Iy 'one_based` is True then the 0x01 bit is returned as 1 instead of 0.
        If `ordination_in_mask` is True then the indices returned will be the
            count of the 1's in the mask that are to the right of the bit rather
            than the total number of digits to the right of the bit. Thus, the
            index will be the index in a taxon block that is the subset of the
            full set of taxa).
    '''
    currBitIndex = one_based and 1 or 0
    test_bit = 1
    maskedSplitRep = s & mask
    standard_ordination = not ordination_in_mask
    while test_bit <= maskedSplitRep:
        if maskedSplitRep & test_bit:
            yield currBitIndex
        if standard_ordination or (mask & test_bit):
            currBitIndex += 1
        test_bit <<= 1

def is_trivial_split(split, mask):
    """Returns True if the split occurs in any tree of the taxa `mask` -- if
    there is only fewer than two 1's or fewer than two 0's in `split` (among
    all of the that are 1 in mask)."""
    masked = split & mask
    if split == 0 or split == mask:
        return True
    if ((masked - 1) & masked) == 0:
        return True
    cm = (~split) & mask
    if ((cm - 1) & cm) == 0:
        return True
    return False

def is_non_singleton_split(split, mask):
    "Returns True if a split is NOT between a leaf and the rest of the taxa,"
    # ((split-1) & split) is True (non-zero) only
    # if split is not a power of 2, i.e., if split
    # has more than one bit turned on, i.e., if it
    # is a non-trivial split.
    return not is_trivial_split(split, mask)

def split_as_string(split_mask, width, symbol1=None, symbol2=None):
    "Returns a 'pretty' split representation."
    s = textprocessing.int_to_bitstring(split_mask).rjust(width, '0')
    if symbol1 is not None:
        s = s.replace('0', symbol1)
    if symbol2 is not None:
        s = s.replace('1', symbol2)
    return s

def split_as_string_rev(split_mask, width, symbol1='.', symbol2='*'):
    """
    Returns a 'pretty' split representation, reversed, with first taxon
    on the left (as given by PAUP*)
    """
    return split_as_string(split_mask=split_mask,
                           width=width,
                           symbol1=symbol1,
                           symbol2=symbol2)[::-1]

def find_edge_from_split(root, split_to_find, mask=-1):
    """Searches for a split_bitmask (in the rooted context -- it does not flip the
    bits) within the subtree descending from `root`.

    Returns None if no such node is found.

    Recursive impl, but should be an order(log(N)) operation."""
    e = root.edge
    cm = e.split_bitmask
    i = cm & split_to_find
    if i != split_to_find:
        return None
    if (mask&cm) == split_to_find:
        return e
    for child in root.child_nodes():
        r = find_edge_from_split(child, split_to_find, mask=mask)
        if r is not None:
            return r
    return None

def encode_splits(tree, create_dict=True, delete_outdegree_one=True):
    """
    Processes splits on a tree, encoding them as bitmask on each edge.
    Adds the following to each edge:
        - `split_bitmask` : a rooted split representation, i.e. a long/bitmask
            where bits corresponding to indices of taxa descended from this
            edge are turned on
    If `create_dict` is True, then the following is added to the tree:
        - `split_edge_map`:
            [if `tree.is_rooted`]: a dictionary where keys are the
            splits and values are edges.
            [otherwise]: a container.NormalizedBitmaskDictionary where the keys are the
            normalized (unrooted) split representations and the values
            are edges. A normalized split_mask is where the split_bitmask
            is complemented if the right-most bit is not '0' (or just
            the split_bitmask otherwise).
    If `delete_outdegree_one` is True then nodes with one
        will be deleted as they are encountered (this is required
        if the split_edge_map dictionary is to refer to all edges in the tree).
        Note this will mean that an unrooted tree like '(A,(B,C))' will
        be changed to '(A,B,C)' after this operation!
    """
    taxon_namespace = tree.taxon_namespace
    if create_dict:
        tree.split_edge_map = {}
        split_map = tree.split_edge_map
        # if tree.is_rooted:
        #     tree.split_edge_map = {}
        # else:
        #     atb = taxon_namespace.all_taxa_bitmask()
        #     d = container.NormalizedBitmaskDict(mask=atb)
        #     tree.split_edge_map = d
        # split_map = tree.split_edge_map
    if not tree.seed_node:
        return

    if delete_outdegree_one:
        sn = tree.seed_node
        if not tree.is_rooted:
            if len(sn._child_nodes) == 2:
                tree.deroot()
        while len(sn._child_nodes) == 1:
            c = sn._child_nodes[0]
            if len(c._child_nodes) == 0:
                break
            try:
                sn.edge.length += c.edge.length
            except:
                pass
            sn.remove_child(c)
            for gc in c._child_nodes:
                sn.add_child(gc)

    for edge in tree.postorder_edge_iter():
        cm = 0
        h = edge.head_node
        child_nodes = h._child_nodes
        nc = len(child_nodes)
        if nc > 0:
            if nc == 1 and delete_outdegree_one and edge.tail_node:
                p = edge.tail_node
                assert(p)
                c = child_nodes[0]
                try:
                    c.edge.length += edge.length
                except:
                    pass
                pos = p._child_nodes.index(h)
                p.insert_child(pos, c)
                p.remove_child(h)
            else:
                for child in child_nodes:
                    cm |= child.edge.split_bitmask
        else:
            t = edge.head_node.taxon
            if t:
                cm = taxon_namespace.taxon_bitmask(t)
        edge.split_bitmask = cm
        if create_dict:
            split_map[cm] = edge
    # create normalized bitmasks, where the full (tree) split mask is *not*
    # all the taxa, but only those found on the tree
    if not tree.is_rooted:
        mask = tree.seed_node.edge.split_bitmask
        d = container.NormalizedBitmaskDict(mask=mask)
        for k, v in tree.split_edge_map.items():
            d[k] = v
        tree.split_edge_map = d

def is_compatible(split1, split2, mask):
    """
    Mask should have 1 for every leaf in the leaf_set
    """
    m1 = mask & split1
    m2 = mask & split2
    if 0 == (m1 & m2):
        return True
    c2 = mask ^ split2
    if 0 == (m1 & c2):
        return True
    c1 = mask ^ split1
    if 0 == (c1 & m2):
        return True
    if 0 == (c1 & c2):
        return True
    return False

def delete_outdegree_one(tree):
    """This function mimics the tree changing operations `encode_splits` but
    without creating the splits dictionary
    """
    if not tree.seed_node:
        return

    sn = tree.seed_node
    if not tree.is_rooted:
        if len(sn.child_nodes()) == 2:
            tree.deroot()
    while len(sn.child_nodes()) == 1:
        c = sn.child_nodes()[0]
        if len(c.child_nodes()) == 0:
            break
        try:
            sn.edge.length += c.edge.length
        except:
            pass
        sn.remove_child(c)
        for gc in c.child_nodes():
            sn.add_child(gc)

    for edge in tree.postorder_edge_iter():
        cm = 0
        h = edge.head_node
        child_nodes = h.child_nodes()
        nc = len(child_nodes)
        if nc > 0:
            if nc == 1 and delete_outdegree_one and edge.tail_node:
                p = edge.tail_node
                assert(p)
                c = child_nodes[0]
                try:
                    c.edge.length += edge.length
                except:
                    pass
                pos = p.child_nodes().index(h)
                p.add_child(c, pos=pos)
                p.remove_child(h)

def lowest_bit_only(split):
    m = split & (split - 1)
    return m ^ split

__n_bits_set = (0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4)
def count_bits(split):
    '''Returns the number of bits set to one.'''
    global __n_bits_set
    c = int(split)
    if c != split:
        raise ValueError('non-integer argument')
    if c < 1:
        if c < 0:
            raise ValueError('negative argument')
        return 0
    n_bits = 0
    while c > 0:
        i = c & 0x0F
        n_bits += __n_bits_set[i]
        c >>= 4
    return n_bits

###############################################################################
## SplitDistribution

class SplitDistribution(object):
    "Collects information regarding splits over multiple trees."

    def __init__(self, taxon_namespace=None, split_set=None):
        self.total_trees_counted = 0
        self.tree_rooting_types_counted = set()
        self.sum_of_tree_weights = 0.0
        if taxon_namespace is not None:
            self.taxon_namespace = taxon_namespace
        else:
            self.taxon_namespace = dendropy.TaxonNamespace()
        self.splits = []
        self.split_counts = {}
        self.weighted_split_counts = {}
        self.split_edge_lengths = {}
        self.split_node_ages = {}
        self.ignore_edge_lengths = False
        self.ignore_node_ages = True
        self.error_on_mixed_rooting_types = True
        self.ultrametricity_precision = 0.0000001
        self._is_rooted = False
        self._split_freqs = None
        self._weighted_split_freqs = None
        self._trees_counted_for_freqs = 0
        self._trees_counted_for_weighted_freqs = 0
        self._split_edge_length_summaries = None
        self._split_node_age_summaries = None
        self._trees_counted_for_summaries = 0
        if split_set:
            for split in split_set:
                self.add_split_count(split, count=1)

    def _is_rooted_deprecation_warning(self):
        deprecate.dendropy_deprecation_warning(
                message="Deprecated since DendroPy 4: 'SplitDistribution.is_rooted' and 'SplitDistribution.is_unrooted' are no longer valid attributes; rooting state tracking and management is now the responsibility of client code.",
                stacklevel=4,
                )
    def _get_is_rooted(self):
        self._is_rooted_deprecation_warning()
        return self._is_rooted
    def _set_is_rooted(self, val):
        self._is_rooted_deprecation_warning()
        self._is_rooted = val
    is_rooted = property(_get_is_rooted, _set_is_rooted)
    def _get_is_unrooted(self):
        self._is_rooted_deprecation_warning()
        return not self._is_rooted
    def _set_is_unrooted(self, val):
        self._is_rooted_deprecation_warning()
        self._is_rooted = not val
    is_unrooted = property(_get_is_unrooted, _set_is_unrooted)

    # def add_split_count(self, split, count=1, weight=None):
    #     if split not in self.splits:
    #         self.splits.append(split)
    #         self.split_counts[split] = 0
    #     self.split_counts[split] += count
    #     if weight is not None:
    #         try:
    #             self.weighted_split_counts[split] += weight
    #         except:
    #             self.weighted_split_counts[split] = weight
    #         ## this is wrong! it adds the weight of the tree
    #         ## multiple times, once for each split in the tree,
    #         ## as opposed to just once for the tree
    #         self.sum_of_tree_weights += weight
    def add_split_count(self, split, count=1):
        if split not in self.splits:
            self.splits.append(split)
            self.split_counts[split] = 0
        self.split_counts[split] += count

    def update(self, split_dist):
        self.total_trees_counted += split_dist.total_trees_counted
        self.sum_of_tree_weights += split_dist.sum_of_tree_weights
        self._split_edge_length_summaries = None
        self._split_node_age_summaries = None
        self._trees_counted_for_summaries = 0
        self.tree_rooting_types_counted.update(split_dist.tree_rooting_types_counted)
        for split in split_dist.splits:
            if split not in self.split_counts:
                self.splits.append(split)
                self.split_counts[split] = split_dist.split_counts[split]
            else:
                self.split_counts[split] += split_dist.split_counts[split]
            if split in split_dist.weighted_split_counts:
                if split not in self.weighted_split_counts:
                    self.weighted_split_counts[split] = split_dist.weighted_split_counts[split]
                else:
                    self.weighted_split_counts[split] += split_dist.weighted_split_counts[split]
            if split in self.split_edge_lengths:
                self.split_edge_lengths[split].extend(split_dist.split_edge_lengths[split])
            elif split in split_dist.split_edge_lengths:
                self.split_edge_lengths[split] = split_dist.split_edge_lengths[split]
            if split in self.split_node_ages:
                self.split_node_ages[split].extend(split_dist.split_node_ages[split])
            elif split in split_dist.split_node_ages:
                self.split_node_ages[split] = split_dist.split_node_ages[split]

    def splits_considered(self):
        """
        Returns 4 values:
            total number of splits counted
            total number of unique splits counted
            total number of non-trivial splits counted
            total number of unique non-trivial splits counted
        """
        if not self.split_counts:
            return 0, 0, 0, 0
        num_splits = 0
        num_unique_splits = 0
        num_nt_splits = 0
        num_nt_unique_splits = 0
        taxa_mask = self.taxon_namespace.all_taxa_bitmask()
        for s in self.split_counts:
            num_unique_splits += 1
            num_splits += self.split_counts[s]
            if is_non_singleton_split(s, taxa_mask):
                num_nt_unique_splits += 1
                num_nt_splits += self.split_counts[s]
        return num_splits, num_unique_splits, num_nt_splits, num_nt_unique_splits

    def __getitem__(self, split_bitmask):
        """
        Returns freqency of split_bitmask.
        """
        return self._get_split_frequencies().get(split_bitmask, 0.0)

    def calc_freqs(self):
        "Forces recalculation of frequencies."
        self._split_freqs = {}
        if self.total_trees_counted == 0:
            for split in self.split_counts.keys():
                self._split_freqs[split] = 1.0
        else:
            total = self.total_trees_counted
            for split in self.split_counts:
                self._split_freqs[split] = float(self.split_counts[split]) / total
        self._trees_counted_for_freqs = self.total_trees_counted
        self._split_edge_length_summaries = None
        self._split_node_age_summaries = None
        return self._split_freqs

    def calc_weighted_freqs(self):
        "Forces recalculation of weighted frequencies."
        self._weighted_split_freqs = {}
        if not self.sum_of_tree_weights:
            total_weight = 1.0
        else:
            total_weight = float(self.sum_of_tree_weights)
        for split in self.weighted_split_counts.keys():
            # sys.stderr.write("{}, {} = {}\n".format(self.weighted_split_counts[split], total_weight, self.weighted_split_counts[split] / total_weight))
            self._weighted_split_freqs[split] = self.weighted_split_counts[split] / total_weight
        self._trees_counted_for_weighted_freqs = self.total_trees_counted
        self._trees_counted_for_summaries = self.total_trees_counted
        return self._weighted_split_freqs

    def _get_split_frequencies(self):
        "Returns dictionary of splits : split frequencies."
        if self._split_freqs is None or self._trees_counted_for_freqs != self.total_trees_counted:
            self.calc_freqs()
        return self._split_freqs
    split_frequencies = property(_get_split_frequencies)

    def _get_weighted_split_frequencies(self):
        "Returns dictionary of splits : weighted_split frequencies."
        if self._weighted_split_freqs is None \
                or self._trees_counted_for_weighted_freqs != self.total_trees_counted:
            self.calc_weighted_freqs()
        return self._weighted_split_freqs
    weighted_split_frequencies = property(_get_weighted_split_frequencies)

    def summarize_edge_lengths(self):
        self._split_edge_length_summaries = {}
        for split, elens in self.split_edge_lengths.items():
            if not elens:
                continue
            try:
                self._split_edge_length_summaries[split] = statistics.summarize(elens)
            except ValueError:
                pass
        return self._split_edge_length_summaries

    def summarize_node_ages(self):
        self._split_node_age_summaries = {}
        for split, ages in self.split_node_ages.items():
            if not ages:
                continue
            try:
                self._split_node_age_summaries[split] = statistics.summarize(ages)
            except ValueError:
                pass
        return self._split_node_age_summaries

    def _get_split_edge_length_summaries(self):
        if self._split_edge_length_summaries is None \
                or self._trees_counted_for_summaries != self.total_trees_counted:
            self.summarize_edge_lengths()
        return dict(self._split_edge_length_summaries)
    split_edge_length_summaries = property(_get_split_edge_length_summaries)

    def _get_split_node_age_summaries(self):
        if self._split_node_age_summaries is None \
                or self._trees_counted_for_summaries != self.total_trees_counted:
            self.summarize_node_ages()
        return dict(self._split_node_age_summaries)
    split_node_age_summaries = property(_get_split_node_age_summaries)

    def count_splits_on_tree(self, tree, is_splits_encoded=False):
        """
        Counts splits in this tree and add to totals. `tree` must be decorated
        with splits, and no attempt is made to normalize taxa.
        """
        assert tree.taxon_namespace is self.taxon_namespace
        self.total_trees_counted += 1
        if not self.ignore_node_ages:
            tree.calc_node_ages(ultrametricity_check_prec=self.ultrametricity_precision)
        if tree.weight is None:
            weight_to_use = 1.0
        else:
            weight_to_use = float(tree.weight)
        self.sum_of_tree_weights += weight_to_use
        if tree.is_rooted:
            self.tree_rooting_types_counted.add(True)
        else:
            self.tree_rooting_types_counted.add(False)
        if not is_splits_encoded:
            tree.update_splits()
        for split in tree.split_edge_map:
            edge = tree.split_edge_map[split]

            ### ??? artifact from a different splits coding scheme ???
            # if self.is_rooted:
            #     split = edge.split_bitmask
            ### IS THIS NECESSARY??? ALL TESTS PASS WITH THIS COMMENTED OUT.
            if tree.is_rooted:
                split = edge.split_bitmask
            ### IS THIS NECESSARY??? ALL TESTS PASS WITH THIS COMMENTED OUT.

            try:
                self.split_counts[split] += 1
            except KeyError:
                self.splits.append(split)
                self.split_counts[split] = 1
            try:
                self.weighted_split_counts[split] += weight_to_use
            except KeyError:
                self.weighted_split_counts[split] = weight_to_use
            if not self.ignore_edge_lengths:
                sel = self.split_edge_lengths.setdefault(split,[])
                if edge.length is not None:
                    sel.append(tree.split_edge_map[split].length)
                # for correct behavior when some or all trees have no edge lengths
#                 else:
#                     self.split_edge_lengths[split].append(0.0)
            if not self.ignore_node_ages:
                sna = self.split_node_ages.setdefault(split, [])
                if edge.head_node is not None:
                    sna.append(edge.head_node.age)

    def is_mixed_rootings_counted(self):
        return ( (True in self.tree_rooting_types_counted)
                and (False in self.tree_rooting_types_counted or None in self.tree_rooting_types_counted) )

    def is_all_counted_trees_rooted(self):
        return (True in self.tree_rooting_types_counted) and (len(self.tree_rooting_types_counted) == 1)

    def is_all_counted_trees_strictly_unrooted(self):
        return (False in self.tree_rooting_types_counted) and (len(self.tree_rooting_types_counted) == 1)

    def is_all_counted_trees_treated_as_unrooted(self):
        return True not in self.tree_rooting_types_counted

    def split_support_iter(self,
            tree,
            is_splits_encoded=False,
            include_external_splits=False,
            traversal_strategy="preorder",
            node_support_attr_name=None,
            edge_support_attr_name=None,
            ):
        """
        Returns iterator over support values for the splits of a given tree,
        where the support value is given by the proportional frequency of the
        split in the current split distribution.

        Parameters
        ----------
        tree : :class:`Tree`
            The :class:`Tree` which will be scored.
        is_splits_encoded : bool
            If `False` [default], then the tree will have its splits encoded or
            updated. Otherwise, if `True`, then the tree is assumed to have its
            splits already encoded and updated.
        include_external_splits : bool
            If `True`, then non-internal split posteriors will be included.
            If `False`, then these are skipped. This should only make a
            difference when dealing with splits collected from trees of
            different leaf sets.
        traversal_strategy : str
            One of: "preorder" or "postorder". Specfies order in which splits
            are visited.

        Returns
        -------
        s : list of floats
            List of values for splits in the tree corresponding to the
            proportional frequency that the split is found in the current
            distribution.
        """
        if traversal_strategy == "preorder":
            if include_external_splits:
                iter_func = tree.preorder_node_iter
            else:
                iter_func = tree.preorder_internal_node_iter
        elif traversal_strategy == "postorder":
            if include_external_splits:
                iter_func = tree.postorder_node_iter
            else:
                iter_func = tree.postorder_internal_node_iter
        else:
            raise ValueError("Traversal strategy not supported: '{}'".format(traversal_strategy))
        if not is_splits_encoded:
            tree.encode_splits()
        split_frequencies = self._get_split_frequencies()
        for nd in iter_func():
            split = nd.edge.split_bitmask
            support = split_frequencies.get(split, 0.0)
            yield support

    def product_of_split_support_on_tree(self,
            tree,
            is_splits_encoded=False,
            include_external_splits=False,
            ):
        """
        Calculates the (log) product of the support of the splits of the
        tree, where the support is given by the proportional frequency of the
        split in the current split distribution.

        The tree that has the highest product of split support out of a sample
        of trees corresponds to the "maximum credibility tree" for that sample.
        This can also be referred to as the "maximum clade credibility tree",
        though this latter term is sometimes use for the tree that has the
        highest *sum* of split support (see
        :meth:`SplitDistribution.sum_of_split_support_on_tree()`).

        Parameters
        ----------
        tree : :class:`Tree`
            The tree for which the score should be calculated.
        is_splits_encoded : bool
            If `True`, then the splits are assumed to have already been encoded
            and will not be updated on the trees.
        include_external_splits : bool
            If `True`, then non-internal split posteriors will be included in
            the score. Defaults to `False`: these are skipped. This should only
            make a difference when dealing with splits collected from trees of
            different leaf sets.

        Returns
        -------
        s : numeric
            The log product of the support of the splits of the tree.
        """
        log_product_of_split_support = 0.0
        for split_support in self.split_support_iter(
                tree=tree,
                is_splits_encoded=is_splits_encoded,
                include_external_splits=include_external_splits,
                traversal_strategy="preorder",
                ):
            if split_support:
                log_product_of_split_support += math.log(split_support)
        return log_product_of_split_support

    def sum_of_split_support_on_tree(self,
            tree,
            is_splits_encoded=False,
            include_external_splits=False,
            ):
        """
        Calculates the sum of the support of the splits of the tree, where the
        support is given by the proportional frequency of the split in the
        current distribtion.

        Parameters
        ----------
        tree : :class:`Tree`
            The tree for which the score should be calculated.
        is_splits_encoded : bool
            If `True`, then the splits are assumed to have already been encoded
            and will not be updated on the trees.
        include_external_splits : bool
            If `True`, then non-internal split posteriors will be included in
            the score. Defaults to `False`: these are skipped. This should only
            make a difference when dealing with splits collected from trees of
            different leaf sets.

        Returns
        -------
        s : numeric
            The sum of the support of the splits of the tree.
        """
        sum_of_split_support = 0.0
        for split_support in self.split_support_iter(
                tree=tree,
                is_splits_encoded=is_splits_encoded,
                include_external_splits=include_external_splits,
                traversal_strategy="preorder",
                ):
            sum_of_split_support += split_support
        return sum_of_split_support

    def _get_taxon_set(self):
        from dendropy import taxonmodel
        taxon_model.taxon_set_deprecation_warning()
        return self.taxon_namespace

    def _set_taxon_set(self, v):
        from dendropy import taxonmodel
        taxon_model.taxon_set_deprecation_warning()
        self.taxon_namespace = v

    def _del_taxon_set(self):
        from dendropy import taxonmodel
        taxon_model.taxon_set_deprecation_warning()

    taxon_set = property(_get_taxon_set, _set_taxon_set, _del_taxon_set)
