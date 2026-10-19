"""Bounded fixed-width HDF5 payload reads without HDF5 filter inflation.

Chunked arrays are assembled from bounded raw chunks. Only unfiltered storage
and a single deflate filter are supported. This deliberately avoids invoking
HDF5's decompressor, which may accept decoded data beyond declared chunk size.
"""
from __future__ import annotations

import itertools
import math
import zlib

import numpy as np


MAX_CHUNKS = 4096
MAX_READ_BYTES = 32 * 1024 * 1024
STORED_SLACK_BYTES = 65536


class StorageReadError(ValueError):
    """The selected HDF5 array exceeds the verified storage representation."""


def _check(condition, message):
    if not condition:
        raise StorageReadError(message)


def _strings(array, file_type):
    if array.dtype.kind != "S":
        return array
    import h5py
    if file_type.get_strpad() == h5py.h5t.STR_NULLTERM:
        # HDF5 C strings end at the first NUL; bytes after it are not part of
        # the logical value, even when a writer leaves nonzero padding there.
        if not array.flags.writeable:
            array = array.copy()
        for index, value in enumerate(array.flat):
            array.flat[index] = bytes(value).split(b"\x00", 1)[0]
    else:
        _check(all(b"\x00" not in bytes(value) for value in array.flat),
               "Noncanonical NULLPAD string interior NUL is unsupported")
    return array


def read_fixed_array(dataset, *, max_bytes=MAX_READ_BYTES, max_stored_bytes=None,
                     max_decoded_bytes=None, max_chunks=MAX_CHUNKS):
    """Return (array, storage receipt) for one bounded fixed-width dataset.

    Sparse/unallocated chunks and unsupported filter combinations are rejected.
    Final edge chunks must decode to their full declared chunk size. No virtual,
    external-storage, variable-length or object arrays are read.
    """
    _check(type(max_bytes) is int and 0 < max_bytes <= MAX_READ_BYTES, "Invalid array read budget")
    if max_stored_bytes is None:
        max_stored_bytes = 2 * max_bytes + STORED_SLACK_BYTES
    _check(type(max_stored_bytes) is int and 0 < max_stored_bytes <= 2 * MAX_READ_BYTES + STORED_SLACK_BYTES,
           "Invalid stored-byte read budget")
    _check(type(max_chunks) is int and 0 < max_chunks <= MAX_CHUNKS, "Invalid chunk count budget")
    if max_decoded_bytes is None:
        max_decoded_bytes = max_bytes
    _check(type(max_decoded_bytes) is int and 0 < max_decoded_bytes <= MAX_READ_BYTES,
           "Invalid decoded-chunk byte budget")
    _check(dataset.shape is not None and dataset.dtype.kind in "biufS" and not dataset.dtype.hasobject
           and dataset.dtype.itemsize > 0, "Only fixed-width numeric and byte-string storage is supported")
    _check(not dataset.is_virtual and not dataset.external, "Virtual/external-storage arrays are unsupported")
    shape, dtype = tuple(dataset.shape), dataset.dtype
    import h5py
    file_type = dataset.id.get_type()
    if dtype.kind == "S":
        _check(file_type.get_class() == h5py.h5t.STRING and not file_type.is_variable_str()
               and file_type.get_strpad() in (h5py.h5t.STR_NULLTERM, h5py.h5t.STR_NULLPAD)
               and file_type.get_cset() in (h5py.h5t.CSET_ASCII, h5py.h5t.CSET_UTF8),
               "Unsupported fixed-string file datatype")
    else:
        # NumPy dtype alone loses HDF5 precision/bit-offset/float-layout rules.
        # Raw reinterpretation is valid only for the canonical file datatype.
        _check(file_type.equal(h5py.h5t.py_create(dtype, logical=True)),
               "Noncanonical numeric HDF5 file datatype is unsupported")
    _check(len(shape) <= 32 and all(0 <= size <= max_bytes for size in shape), "Array dimension limit exceeded")
    output_bytes = math.prod(shape) * dtype.itemsize
    _check(output_bytes <= max_bytes, "Array logical byte budget exceeded")
    properties = dataset.id.get_create_plist()
    filters = [int(properties.get_filter(index)[0]) for index in range(properties.get_nfilters())]
    _check(filters in ([], [1]), "Only unfiltered storage or a single deflate filter is supported")
    receipt = {"filter_ids": filters, "logical_bytes": output_bytes, "stored_bytes_read": 0,
               "chunks_read": 0, "decoded_chunk_bytes": 0, "hdf5_filter_decode_invoked": False}
    if dataset.chunks is None:
        _check(not filters, "Filtered contiguous storage is unsupported")
        _check(output_bytes <= max_stored_bytes, "Stored byte budget exceeded")
        _check(output_bytes <= max_decoded_bytes, "Decoded byte budget exceeded")
        _check(output_bytes == 0 or dataset.id.get_storage_size() == output_bytes,
               "Unallocated or unexpected contiguous/compact storage is unsupported")
        # Fixed-width contiguous/compact arrays have no decompression pipeline.
        array = np.asarray(dataset[()])
        _check(array.shape == shape and array.nbytes == output_bytes, "Unexpected contiguous array result")
        receipt.update(layout="unfiltered_contiguous_or_compact", stored_bytes_read=output_bytes,
                       decoded_chunk_bytes=output_bytes)
        return _strings(array, file_type), receipt

    chunks = tuple(dataset.chunks)
    chunk_bytes = math.prod(chunks) * dtype.itemsize
    _check(len(chunks) == len(shape) and all(size > 0 for size in chunks)
           and chunk_bytes <= max_bytes, "Array chunk byte budget exceeded")
    chunk_count = math.prod((size + chunk - 1) // chunk for size, chunk in zip(shape, chunks))
    _check(chunk_count <= max_chunks, "Array chunk count budget exceeded")
    _check(chunk_count * chunk_bytes <= max_decoded_bytes, "Aggregate decoded chunk byte budget exceeded")
    _check(dataset.id.get_num_chunks() == chunk_count, "Sparse/unallocated or extra allocated chunks are unsupported")
    array = np.empty(shape, dtype=dtype)
    receipt.update(layout="bounded_raw_chunk_assembly", decoded_chunk_bytes=chunk_count * chunk_bytes)
    if chunk_count == 0:
        return _strings(array, file_type), receipt
    ranges = [range(0, size, chunk) for size, chunk in zip(shape, chunks)]
    for coordinate in itertools.product(*ranges):
        info = dataset.id.get_chunk_info_by_coord(coordinate)
        _check(info.byte_offset is not None and 0 < info.size <= chunk_bytes + STORED_SLACK_BYTES,
               "Unallocated or oversized stored chunk is unsupported")
        _check(tuple(info.chunk_offset) == coordinate, "Unexpected stored chunk coordinate")
        _check(receipt["stored_bytes_read"] + info.size <= max_stored_bytes, "Stored byte budget exceeded")
        mask, raw = dataset.id.read_direct_chunk(coordinate)
        _check(len(raw) == info.size and mask == info.filter_mask, "Stored chunk metadata changed during read")
        _check(mask == 0 or (filters == [1] and mask == 1), "Unsupported chunk filter mask")
        receipt["stored_bytes_read"] += len(raw)
        receipt["chunks_read"] += 1
        if filters == [1] and mask == 0:
            try:
                inflater = zlib.decompressobj()
                decoded = inflater.decompress(raw, chunk_bytes + 1)
            except zlib.error as error:
                raise StorageReadError("Invalid raw deflate chunk") from error
            _check(len(decoded) == chunk_bytes and inflater.eof and not inflater.unused_data
                   and not inflater.unconsumed_tail, "Deflate chunk size or stream boundary mismatch")
        else:
            decoded = raw
            _check(len(decoded) == chunk_bytes, "Unfiltered chunk size mismatch")
        block = np.frombuffer(decoded, dtype=dtype).reshape(chunks)
        lengths = tuple(min(chunk, size - start) for start, size, chunk in zip(coordinate, shape, chunks))
        target = tuple(slice(start, start + length) for start, length in zip(coordinate, lengths))
        source = tuple(slice(0, length) for length in lengths)
        array[target] = block[source]
    return _strings(array, file_type), receipt
