#
# Copyright 2020 NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Classes for reading and writing VCFs."""


from dataclasses import dataclass
import vcf
import warnings

from variantworks.io.baseio import BaseReader
from variantworks.types import VariantZygosity, VariantType, Variant


class VCFReader(BaseReader):
    """Reader for VCF files."""

    @dataclass
    class VcfBamPath:
        """Data class encapsulating paired VCF and BAM inputs."""
        vcf: str
        bam: str
        is_fp: bool = False

    def __init__(self, vcf_bam_list):
        """Parse and extract variants from a vcf/bam tuple.

        Args:
            vcf_bam_list: A list of VcfBamPath namedtuple specifying VCF file and corresponding BAM file.
                           The VCF file must be bgzip compressed and indexed.

        Returns:
           Instance of class.
        """
        super().__init__()
        self._labels = []
        for elem in vcf_bam_list:
            assert (elem.vcf is not None and elem.bam is not None and type(
                elem.is_fp) is bool)
            self._parse_vcf(elem.vcf, elem.bam, self._labels, elem.is_fp)

    def __getitem__(self, idx):
        """Get Variant instance in location.

        Args:
            idx: Variant index
        Returns:
            Variant instance
        """
        return self._labels[idx]

    def __len__(self):
        """Return number of Varint objects."""
        return len(self._labels)

    @staticmethod
    def _get_variant_zygosity(record, is_fp=False):
        """Determine variant type from pyvcf record.

        False positive variants are considered NO_VARIANT entries.

        Args:
            record : a pyVCF record.
            is_fp : is the record a false positive variant.

        Returns:
            A variant type
        """
        if is_fp:
            return VariantZygosity.NO_VARIANT
        if record.num_het > 0:
            return VariantZygosity.HETEROZYGOUS
        elif record.num_hom_alt > 0:
            return VariantZygosity.HOMOZYGOUS
        raise ValueError("Unexpected variant zygosity - {}, num_het - {}, num_hom_alt - {}".format(
            record, record.num_het, record.num_hom_alt))

    @staticmethod
    def _get_variant_type(record):
        """Determine variant type.

        Args:
            record : pyVCF entry.

        Returns:
            Type of variant - SNP, INSERTION or DELETION
        """
        if record.is_snp:
            return VariantType.SNP
        elif record.is_indel:
            if record.is_deletion:
                return VariantType.DELETION
            else:
                return VariantType.INSERTION
        raise ValueError("Unexpected variant type - {}".format(record))

    def _create_variant_tuple_from_record(self, record, vcf_file, bam, is_fp):
        """Create a variant record from pyVCF record.

        Args:
            record : pyVCF record
            vcf_file : Path to VCF file
            bam : Path to corresponding BAM file
            is_fp : Boolean indicating whether entry is a false positive variant or not.

        Returns:
           Variant dataclass record.
        """
        var_zyg = self._get_variant_zygosity(record, is_fp)
        var_type = self._get_variant_type(record)
        # Split multi alleles into multiple entries
        for alt in record.ALT:
            var_allele = alt.sequence
            try:
                var_format = record.FORMAT.split(':')
            except AttributeError:
                if is_fp:
                    var_format = []
                else:
                    raise RuntimeError("Could not parse format field for entry - {}".format(record))

            try:
                yield Variant(chrom=record.CHROM, pos=record.POS, id=record.ID, ref=record.REF,
                              allele=var_allele, quality=record.QUAL, filter=record.FILTER,
                              info=record.INFO, format=var_format,
                              samples=[[field_value for field_value in sample.data]
                                       for sample in record.samples],
                              zygosity=var_zyg, type=var_type, vcf=vcf_file, bam=bam)
            except Exception:
                raise RuntimeError(
                    "Could not parse variant from entry - {}".format(record))

    @staticmethod
    def _get_file_reader(vcf_file_object=None, vcf_file_path=None):
        """Create VCF file reader from file object or file path.

        Args:
            vcf_file_object: VCF file object
            vcf_file_path: VCF file path

        Returns:
            pyVCF Reader iterator
        """
        if not (vcf_file_object or vcf_file_path):
            raise RuntimeError('You must provide at least one - file object or file path to the vcf reader')
        if vcf_file_path:
            # Check for compressed file
            assert (vcf_file_path[-3:] == ".gz"), "VCF file needs to be compressed and indexed"
        return vcf.Reader(vcf_file_object, vcf_file_path)

    def _parse_vcf(self, vcf_file, bam, labels, is_fp=False):
        """Parse VCF file and retain labels after they have passed filters.

        Args:
            vcf_file : Path to VCF file.
            bam : Path to BAM file for VCF.
            labels : List to store parsed variant records.
            is_fp : Boolean to indicate if file is for false positive variants.
        """
        vcf_reader = self._get_file_reader(vcf_file_path=vcf_file)
        if not is_fp and len(vcf_reader.samples) != 1:
            raise RuntimeError(
                "Can not parse: {}. VariantWorks currently only supports single sample VCF files".format(vcf_file))
        for record in vcf_reader:
            if not is_fp and record.num_called < len(vcf_reader.samples):
                raise RuntimeError(
                    "Can not parse record %s in %s, all samples must be called in true positive VCF file" % (
                        record, vcf_file)
                )
            if not record.is_snp:
                warnings.warn("%s is filtered - not an SNP record" % record)
                continue
            if len(record.ALT) > 1:
                warnings.warn(
                    "%s is filtered - multiallele recrods are not supported" % record)
                continue
            for variant in self._create_variant_tuple_from_record(record, vcf_file, bam, is_fp):
                labels.append(variant)
