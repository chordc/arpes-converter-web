import io
import json
import struct
import traceback
from typing import Any, Dict, Tuple

import numpy as np
import re
import zipfile
import posixpath

MAXDIMS = 4
def _read_pxt_wave_axes_from_binary(input_bytes: bytes):
    """
    从当前这类 SES/PXT 文件的二进制 wave 头中读取:
    - e_num, y_num
    - e_delta, y_delta
    - e_offset, y_offset

    这版是按你上传的真实样本定位出来的。
    """
    if len(input_bytes) < 204:
        raise ValueError("PXT file is too small to contain the expected binary wave header.")

    # 维度
    e_num = struct.unpack("<I", input_bytes[140:144])[0]
    y_num = struct.unpack("<I", input_bytes[144:148])[0]

    # 步长
    e_delta = struct.unpack("<d", input_bytes[156:164])[0]
    y_delta = struct.unpack("<d", input_bytes[164:172])[0]

    # 起点
    e_offset = struct.unpack("<d", input_bytes[188:196])[0]
    y_offset = struct.unpack("<d", input_bytes[196:204])[0]

    e_axis = e_offset + e_delta * np.arange(e_num, dtype=np.float32)
    y_axis = y_offset + y_delta * np.arange(y_num, dtype=np.float32)

    info = {
        "e_num": int(e_num),
        "y_num": int(y_num),
        "e_delta": float(e_delta),
        "y_delta": float(y_delta),
        "e_offset": float(e_offset),
        "y_offset": float(y_offset),
    }

    return y_num, e_num, y_axis, e_axis, info

def _parse_ses_text_header_from_pxt(input_bytes: bytes) -> Dict[str, str]:
    marker = b"[SES]"
    idx = input_bytes.find(marker)
    if idx < 0:
        raise ValueError("No [SES] header found in PXT file.")

    text = input_bytes[idx:].decode("latin1", errors="ignore")
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]

    header = {}
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            header[k.strip()] = v.strip()

    header["_text_start"] = str(idx)
    return header


def _ses_header_to_dims_and_axes(header: Dict[str, str], input_bytes: bytes):
    """
    对当前这类 PXT：
    - 优先从 binary wave header 读取真实坐标轴
    - 文本 [SES] footer 仅作为校验/兜底
    """
    # 先从 binary 里读真实轴
    y_num_bin, e_num_bin, y_axis, e_axis, bin_info = _read_pxt_wave_axes_from_binary(input_bytes)

    # 再从文本 footer 读一份能量信息做校验
    low_energy = float(header["Low Energy"])
    high_energy = float(header["High Energy"])
    energy_step = float(header["Energy Step"])
    e_num_txt = int(round((high_energy - low_energy) / energy_step)) + 1

    # 若 binary 读出的 e_num 和文本 header 不一致，给出显式报错
    if e_num_bin != e_num_txt:
        raise ValueError(
            f"PXT energy dimension mismatch: binary header says {e_num_bin}, "
            f"text header says {e_num_txt}."
        )

    return y_num_bin, e_num_bin, y_axis, e_axis

def _read_ses_pxt_matrix(input_bytes: bytes, y_num: int, e_num: int):
    data_offset = 392
    expected_points = y_num * e_num
    expected_bytes = expected_points * 4  # float32

    raw = input_bytes[data_offset:data_offset + expected_bytes]
    if len(raw) != expected_bytes:
        raise ValueError(
            f"PXT data size mismatch: expected {expected_bytes} bytes, got {len(raw)} bytes."
        )

    arr = np.frombuffer(raw, dtype="<f4")
    mat = arr.reshape(y_num, e_num)
    return mat

def _da30_norm_zip_path(name: str) -> str:
    return str(name).replace("\\", "/").strip("/")


def _da30_find_member_name(zf: zipfile.ZipFile, target: str) -> str:
    """
    在 zip 内按规范化路径查找文件，兼容大小写和相对路径。
    """
    target_norm = _da30_norm_zip_path(target)
    names = zf.namelist()
    norm_map = {_da30_norm_zip_path(n): n for n in names}

    if target_norm in norm_map:
        return norm_map[target_norm]

    target_lower = target_norm.lower()
    for norm_name, raw_name in norm_map.items():
        if norm_name.lower() == target_lower:
            return raw_name

    # 再尝试只按 basename 匹配
    target_base = posixpath.basename(target_norm).lower()
    candidates = [
        raw_name for norm_name, raw_name in norm_map.items()
        if posixpath.basename(norm_name).lower() == target_base
    ]
    if len(candidates) == 1:
        return candidates[0]

    raise FileNotFoundError(f"File not found inside DA30 zip: {target}")


def _da30_read_text_from_zip(zf: zipfile.ZipFile, member_name: str) -> str:
    raw = zf.read(member_name)
    for enc in ("utf-8", "gbk", "latin1"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


def _da30_get_header_value(text: str, key: str, mode: int, num: int = 0):
    """
    mode=0 -> float
    mode=1 -> str
    """
    lines = re.findall(rf"^{re.escape(key)}.*$", text, flags=re.MULTILINE)
    if not lines:
        raise KeyError(f"Key '{key}' not found in DA30 header.")
    if num >= len(lines):
        raise IndexError(f"Key '{key}' occurrence {num} not found in DA30 header.")

    value = lines[num].split("=", 1)[1].strip()

    if mode == 0:
        return float(value)
    if mode == 1:
        return value
    return None


def _da30_resolve_relative_path(base_member: str, relative_name: str) -> str:
    base_dir = posixpath.dirname(_da30_norm_zip_path(base_member))
    rel = _da30_norm_zip_path(relative_name)
    if not base_dir:
        return rel
    return posixpath.normpath(posixpath.join(base_dir, rel))


def _da30_parse_bundle(input_bytes: bytes):
    """
    从 DA30 zip 中解析出:
    - data: (theta, phi, energy)
    - axes: [theta_axis, phi_axis, energy_axis]
    - info: metadata/debug info
    """
    with zipfile.ZipFile(io.BytesIO(input_bytes), "r") as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("DA30 zip is empty.")

        # 1) 找 viewer.ini
        viewer_candidates = [n for n in names if posixpath.basename(n).lower() == "viewer.ini"]
        if not viewer_candidates:
            raise FileNotFoundError("viewer.ini not found in DA30 zip.")

        viewer_member = viewer_candidates[0]
        viewer_text = _da30_read_text_from_zip(zf, viewer_member)

        # 2) 从 viewer.ini 读路径和维度
        ini_rel = _da30_get_header_value(viewer_text, "ini_path", mode=1)
        data_rel = _da30_get_header_value(viewer_text, "path", mode=1)

        e_num = int(_da30_get_header_value(viewer_text, "width", 0))
        phi_num = int(_da30_get_header_value(viewer_text, "height", 0))
        theta_num = int(_da30_get_header_value(viewer_text, "depth", 0))

        e_offset = _da30_get_header_value(viewer_text, "width_offset", 0)
        e_delta = _da30_get_header_value(viewer_text, "width_delta", 0)
        e_label = _da30_get_header_value(viewer_text, "width_label", 1)

        phi_offset = _da30_get_header_value(viewer_text, "height_offset", 0)
        phi_delta = _da30_get_header_value(viewer_text, "height_delta", 0)
        phi_label = _da30_get_header_value(viewer_text, "height_label", 1)

        theta_offset = _da30_get_header_value(viewer_text, "depth_offset", 0)
        theta_delta = _da30_get_header_value(viewer_text, "depth_delta", 0)
        theta_label = _da30_get_header_value(viewer_text, "depth_label", 1)

        # 3) 找 region ini 和数据文件
        ini_member = _da30_find_member_name(
            zf, _da30_resolve_relative_path(viewer_member, ini_rel)
        )
        data_member = _da30_find_member_name(
            zf, _da30_resolve_relative_path(viewer_member, data_rel)
        )

        region_text = _da30_read_text_from_zip(zf, ini_member)
        raw_data = zf.read(data_member)

        expected_points = theta_num * phi_num * e_num

        # 优先尝试 int32；如果不匹配，再尝试 int64
        arr = None
        chosen_dtype = None
        for dtype in ("<i4", "<i8"):
            itemsize = np.dtype(dtype).itemsize
            if len(raw_data) == expected_points * itemsize:
                arr = np.frombuffer(raw_data, dtype=dtype)
                chosen_dtype = dtype
                break

        if arr is None:
            # 兜底：尽量按 int32 读，再检查长度
            arr = np.frombuffer(raw_data, dtype="<i4")
            chosen_dtype = "<i4"
            if arr.size != expected_points:
                raise ValueError(
                    f"DA30 data size mismatch: expected {expected_points} points, "
                    f"got {arr.size} points from {len(raw_data)} bytes."
                )

        mat = arr.reshape(theta_num, phi_num, e_num)

        e_axis = e_offset + e_delta * np.arange(e_num, dtype=np.float32)
        phi_axis = phi_offset + phi_delta * np.arange(phi_num, dtype=np.float32)
        theta_axis = theta_offset + theta_delta * np.arange(theta_num, dtype=np.float32)

        info = {
            "viewer_ini_member": viewer_member,
            "region_ini_member": ini_member,
            "data_member": data_member,
            "viewer_ini": {
                "e_num": e_num,
                "phi_num": phi_num,
                "theta_num": theta_num,
                "e_offset": e_offset,
                "e_delta": e_delta,
                "e_label": e_label,
                "phi_offset": phi_offset,
                "phi_delta": phi_delta,
                "phi_label": phi_label,
                "theta_offset": theta_offset,
                "theta_delta": theta_delta,
                "theta_label": theta_label,
            },
            "region_info": {
                "Version": _da30_get_header_value(region_text, "Version", 1),
                "Region Name": _da30_get_header_value(region_text, "Region Name", 1),
                "Lens Mode": _da30_get_header_value(region_text, "Lens Mode", 1),
                "Pass Energy": _da30_get_header_value(region_text, "Pass Energy", 1),
                "Acquisition Mode": _da30_get_header_value(region_text, "Acquisition Mode", 1),
                "Instrument": _da30_get_header_value(region_text, "Instrument", 1),
                "Location": _da30_get_header_value(region_text, "Location", 1),
                "User": _da30_get_header_value(region_text, "User", 1),
                "Sample": _da30_get_header_value(region_text, "Sample", 1),
                "Date": _da30_get_header_value(region_text, "Date", 1),
                "Time": _da30_get_header_value(region_text, "Time", 1),
            },
            "binary_dtype": chosen_dtype,
        }

        return (
            np.asarray(mat, dtype=np.float32),
            [theta_axis, phi_axis, e_axis],
            info,
        )

def _parse_itx_dim_tokens(lines):
    """
    从 ITX 第二行附近解析维度信息。
    兼容你原先 get_maxrow() 的逻辑：
    - 2 个数字: 2D
    - 3 个数字: 3D（原代码按 result[0] * result[2] 读入）
    - 其他: 视作 1D
    """
    if len(lines) < 2:
        return []

    line = lines[1]
    m = re.findall(r".*=(.*)\t", line)
    if m:
        nums = re.findall(r"\d+", m[0])
        return nums
    return []


def _compute_itx_data_rows(lines, dim_tokens):
    """
    计算数据区行数，保持与你原始类一致：
    - 2D: max_row = result[0]
    - 3D: max_row = result[0] * result[2]
    - 1D: max_row = len(lines) - 5
    """
    if len(dim_tokens) == 2:
        return int(dim_tokens[0])
    elif len(dim_tokens) == 3:
        return int(dim_tokens[0]) * int(dim_tokens[2])
    else:
        return max(len(lines) - 5, 0)


def _parse_itx_axes(lines, max_row, dim_tokens):
    """
    从 ITX 文本中解析 SetScale/P x/y/z(d) 轴信息。
    兼容类似：
        X SetScale/P x -0.6,0.003,"", wave;
          SetScale/P y -0.487,0.002,"", wave;
          SetScale d 0,0,"", wave
    """
    axes_meta = {}
    axis_arrays = {}

    text = "".join(lines)

    def _extract_scale(axis_name):
        """
        匹配:
            SetScale/P x start,delta,"unit", wave
        或:
            SetScale x start,delta,"unit", wave
        """
        patterns = [
            rf"SetScale\s*/P\s*{axis_name}\s+([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*\"([^\"]*)\"",
            rf"SetScale\s+{axis_name}\s+([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*\"([^\"]*)\"",
        ]
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                start = float(m.group(1))
                delta = float(m.group(2))
                unit = m.group(3)
                return start, delta, unit
        return None

    # 维度长度：与你现有逻辑保持一致
    dims = []
    try:
        if len(dim_tokens) == 2:
            dims = [int(dim_tokens[0]), int(dim_tokens[1])]
        elif len(dim_tokens) == 3:
            dims = [int(dim_tokens[0]), int(dim_tokens[1]), int(dim_tokens[2])]
        elif len(dim_tokens) == 1:
            dims = [int(dim_tokens[0])]
    except Exception:
        dims = []

    # 依次尝试 x/y/z；第三维有时也可能写成 d
    scale_x = _extract_scale("x")
    scale_y = _extract_scale("y")
    scale_z = _extract_scale("z")
    scale_d = _extract_scale("d")

    def _build_axis(start, delta, n):
        return start + delta * np.arange(n, dtype=np.float32)

    if len(dims) >= 1 and scale_x is not None:
        start, delta, unit = scale_x
        axes_meta["axis_0_meta"] = {
            "scale_var": "x",
            "start": start,
            "delta": delta,
            "unit": unit,
            "length": dims[0],
        }
        axis_arrays["axis_0"] = _build_axis(start, delta, dims[0])

    if len(dims) >= 2 and scale_y is not None:
        start, delta, unit = scale_y
        axes_meta["axis_1_meta"] = {
            "scale_var": "y",
            "start": start,
            "delta": delta,
            "unit": unit,
            "length": dims[1],
        }
        axis_arrays["axis_1"] = _build_axis(start, delta, dims[1])

    if len(dims) >= 3:
        scale3 = scale_z if scale_z is not None else scale_d
        if scale3 is not None:
            start, delta, unit = scale3
            axes_meta["axis_2_meta"] = {
                "scale_var": "z" if scale_z is not None else "d",
                "start": start,
                "delta": delta,
                "unit": unit,
                "length": dims[2],
            }
            axis_arrays["axis_2"] = _build_axis(start, delta, dims[2])

    return axes_meta, axis_arrays


def _load_itx_data_array(text, max_row, dim_tokens):
    """
    读取 ITX 数据区。
    保持原类逻辑：
    - skiprows=3
    - max_rows=max_row
    - 3D 时 reshape 为 (result[2], result[0], result[1])
    """
    if max_row <= 0:
        return np.array([], dtype=np.float32)

    data = np.loadtxt(io.StringIO(text), skiprows=3, max_rows=max_row)

    if len(dim_tokens) == 2:
        data = data.T
    elif len(dim_tokens) == 3:
        nx = int(dim_tokens[0])
        ny = int(dim_tokens[1])
        nz = int(dim_tokens[2])
        data = np.reshape(data, (nz, nx, ny))

    return np.asarray(data, dtype=np.float32)

def _ok_meta(
    input_format: str,
    output_format: str,
    input_size_bytes: int,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    meta = {
        "success": True,
        "input_format": input_format,
        "output_format": output_format,
        "input_size_bytes": input_size_bytes,
    }
    if extra:
        meta.update(extra)
    return meta


def _error_meta(
    input_format: str,
    output_format: str,
    input_size_bytes: int,
    error: Exception,
) -> Dict[str, Any]:
    return {
        "success": False,
        "input_format": input_format,
        "output_format": output_format,
        "input_size_bytes": input_size_bytes,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "traceback": traceback.format_exc(),
    }


def _normalize_options(options: Dict[str, Any] | None) -> Dict[str, Any]:
    options = options or {}

    custom_metadata = options.get("custom_metadata", {}) or {}
    if not isinstance(custom_metadata, dict):
        custom_metadata = {}

    return {
        "axis_labels": options.get("axis_labels", []) or [],
        "axis_units": options.get("axis_units", []) or [],
        "experiment_date": options.get("experiment_date", "") or "",
        "measurement_datetime": options.get("measurement_datetime", "") or "",
        "location": options.get("location", "") or "",
        "hv": options.get("hv", "") or "",
        "slit": options.get("slit", "") or "",
        "metadata_mode": options.get("metadata_mode", "preserve") or "preserve",
        "output_name": options.get("output_name", "") or "",
        "sample_name": options.get("sample_name", "") or "",
        "operator": options.get("operator", "") or "",
        "temperature_K": options.get("temperature_K", "") or "",
        "photon_energy_eV": options.get("photon_energy_eV", "") or options.get("hv", "") or "",
        "bias_voltage_V": options.get("bias_voltage_V", "") or "",
        "polarization": options.get("polarization", "") or "",
        "notes": options.get("notes", "") or "",
        "custom_metadata": custom_metadata,
    }


def _save_npz_bytes(**arrays: Any) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def _load_npz_bytes(data: bytes) -> Dict[str, np.ndarray]:
    buf = io.BytesIO(data)
    with np.load(buf, allow_pickle=False) as npz:
        return {k: npz[k] for k in npz.files}


def _safe_scalar_from_npz_value(value: Any):
    if isinstance(value, np.ndarray) and value.shape == ():
        return value.item()
    return value


def _normalize_axis_metadata(values: list[Any], ndim: int, fill_value: str = "") -> list[str]:
    values = [str(v) for v in values[:ndim]]
    if len(values) < ndim:
        values.extend([fill_value] * (ndim - len(values)))
    return values


def _build_meta_dict(
    *,
    source_format: str,
    data: np.ndarray,
    axis_labels: list[str],
    axis_units: list[str],
    metadata_mode: str,
    experiment_date: str,
    measurement_datetime: str,
    location: str,
    hv: str,
    slit: str,
    sample_name: str,
    operator: str,
    temperature_K: Any,
    photon_energy_eV: Any,
    bias_voltage_V: Any,
    polarization: str,
    notes: str,
    custom_metadata: Dict[str, Any] | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    ndim = int(data.ndim)

    base_meta = {
        "format_version": "1.0",
        "source_format": source_format,
        "data_shape": list(data.shape),
        "data_dtype": str(data.dtype),
        "ndim": ndim,
    }

    if metadata_mode == "minimal":
        if extra:
            for key, value in extra.items():
                if key in ("is_complex",):
                    base_meta[key] = value
        return base_meta

    base_meta.update(
        {
            "axis_labels": _normalize_axis_metadata(axis_labels, ndim, ""),
            "axis_units": _normalize_axis_metadata(axis_units, ndim, ""),
            "experiment": {
                "date": experiment_date,
                "datetime": measurement_datetime,
                "location": location,
                "hv": hv,
                "slit": slit,
                "sample_name": sample_name,
                "operator": operator,
                "temperature_K": temperature_K,
                "photon_energy_eV": photon_energy_eV,
                "bias_voltage_V": bias_voltage_V,
                "polarization": polarization,
                "notes": notes,
            },
            "custom_metadata": custom_metadata or {},
        }
    )

    if extra:
        base_meta.update(extra)

    return base_meta


def _meta_json_array(meta_dict: Dict[str, Any]) -> np.ndarray:
    return np.array(json.dumps(meta_dict, ensure_ascii=False))


def _preview_numeric_array(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data)
    if np.iscomplexobj(arr):
        arr = np.abs(arr)
    return np.asarray(arr, dtype=np.float64)


def _downsample_indices(length: int, target: int) -> np.ndarray:
    if length <= target:
        return np.arange(length, dtype=np.int64)
    return np.linspace(0, length - 1, target, dtype=np.int64)


def _build_preview_payload(data: np.ndarray, axes: list[np.ndarray] | None = None) -> Dict[str, Any]:
    axes = axes or []
    arr = np.asarray(data)
    ndim = int(arr.ndim)

    preview: Dict[str, Any] = {
        "ndim": ndim,
        "shape": list(arr.shape),
    }

    if ndim == 0:
        preview["scalar"] = _safe_scalar_from_npz_value(arr)
        return preview

    arr_num = _preview_numeric_array(arr)

    if ndim == 1:
        idx = _downsample_indices(arr_num.shape[0], 1024)
        y = arr_num[idx]
        if len(axes) >= 1 and isinstance(axes[0], np.ndarray) and axes[0].shape[0] == arr_num.shape[0]:
            x = np.asarray(axes[0])[idx]
        else:
            x = idx.astype(np.float64)

        preview.update(
            {
                "x": x.tolist(),
                "y": y.tolist(),
                "x_source": "axis_0" if len(axes) >= 1 else "index",
            }
        )
        return preview

    if ndim == 2:
        row_idx = _downsample_indices(arr_num.shape[0], 256)
        col_idx = _downsample_indices(arr_num.shape[1], 256)
        image_small = arr_num[np.ix_(row_idx, col_idx)]

        preview.update(
            {
                "image_small": image_small.tolist(),
                "preview_shape": list(image_small.shape),
                "row_source": "axis_0" if len(axes) >= 1 else "index",
                "col_source": "axis_1" if len(axes) >= 2 else "index",
            }
        )
        return preview

    if ndim == 3:
        preview["message"] = "3D preview should be opened in viewer.html."
        return preview

    preview["message"] = "Preview is only generated automatically for 1D, 2D, or 3D data."
    return preview


def _extract_npz_axes(arrays: Dict[str, np.ndarray], ndim: int) -> list[np.ndarray]:
    axes = []
    for i in range(ndim):
        axis = arrays.get(f"axis_{i}")
        if isinstance(axis, np.ndarray) and axis.ndim == 1:
            axes.append(axis)
    return axes


def _ibw_bytes_to_array_and_axes(input_bytes: bytes):
    buf = io.BytesIO(input_bytes)

    bh = buf.read(64)     # BinHeader5
    wh = buf.read(320)    # WaveHeader5

    NT_CMPLX = 0x01
    NT_FP32 = 0x02
    NT_FP64 = 0x04
    NT_I8 = 0x08
    NT_I16 = 0x10
    NT_I32 = 0x20
    NT_UNSIGNED = 0x40

    dims = [struct.unpack('<i', wh[68 + 4 * i: 72 + 4 * i])[0] for i in range(MAXDIMS)]
    dims = [d for d in dims if d > 0]
    ndim = len(dims)

    if ndim == 0:
        raise ValueError("IBW contains no valid dimensions.")

    total_points = struct.unpack('<i', wh[12:16])[0]
    data_type = struct.unpack('<H', wh[16:18])[0]

    is_complex = bool(data_type & NT_CMPLX)
    is_unsigned = bool(data_type & NT_UNSIGNED)
    base_type = data_type & ~(NT_CMPLX | NT_UNSIGNED)

    if base_type == NT_FP32:
        dtype = '<f4'
    elif base_type == NT_FP64:
        dtype = '<f8'
    elif base_type == NT_I8:
        dtype = '<u1' if is_unsigned else '<i1'
    elif base_type == NT_I16:
        dtype = '<u2' if is_unsigned else '<i2'
    elif base_type == NT_I32:
        dtype = '<u4' if is_unsigned else '<i4'
    else:
        raise ValueError(f"Unsupported IBW data type bitmask: {data_type}")

    points = int(np.prod(dims))
    scalar_count = points * (2 if is_complex else 1)
    data_bytes = scalar_count * np.dtype(dtype).itemsize
    raw_data = buf.read(data_bytes)

    if len(raw_data) != data_bytes:
        raise ValueError(
            f"Unexpected IBW data size: expected {data_bytes} bytes, got {len(raw_data)} bytes."
        )

    arr = np.frombuffer(raw_data, dtype=dtype)

    if is_complex:
        re = arr[0::2]
        im = arr[1::2]

        if base_type == NT_FP32:
            mat = (
                re.astype(np.float32, copy=False)
                + 1j * im.astype(np.float32, copy=False)
            ).reshape(dims, order="F")
        elif base_type == NT_FP64:
            mat = (
                re.astype(np.float64, copy=False)
                + 1j * im.astype(np.float64, copy=False)
            ).reshape(dims, order="F")
        else:
            mat = (
                re.astype(np.float64) + 1j * im.astype(np.float64)
            ).reshape(dims, order="F")
    else:
        mat = arr.reshape(dims, order="F")

    axes = []
    for i in range(ndim):
        delta = struct.unpack("<d", wh[84 + i * 8: 92 + i * 8])[0]
        offset = struct.unpack("<d", wh[116 + i * 8: 124 + i * 8])[0]
        axis = offset + delta * np.arange(dims[i])
        axes.append(axis)

    # -------- 修正 2D 方向 --------
    if ndim == 2:
        mat = mat.T
        if len(axes) >= 2:
            axes[0], axes[1] = axes[1], axes[0]

    ibw_info = {
        "dims": dims,
        "ndim": ndim,
        "total_points_header": int(total_points),
        "dtype": str(mat.dtype),
        "is_complex": bool(is_complex),
        "is_unsigned": bool(is_unsigned),
        "base_type": int(base_type),
    }

    return mat, axes, ibw_info


# -----------------------------
# Real / placeholder converters
# -----------------------------

def _convert_npz_to_npz(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    arrays = _load_npz_bytes(input_bytes)
    output_bytes = _save_npz_bytes(**arrays)

    shapes = {k: list(v.shape) for k, v in arrays.items() if isinstance(v, np.ndarray)}
    dtypes = {k: str(v.dtype) for k, v in arrays.items() if isinstance(v, np.ndarray)}

    meta_json_preview = None
    if "meta_json" in arrays:
        raw_meta = _safe_scalar_from_npz_value(arrays["meta_json"])
        try:
            meta_json_preview = json.loads(raw_meta)
        except Exception:
            meta_json_preview = str(raw_meta)

    data = arrays.get("data")
    preview = None
    ndim = None
    axis_keys = [k for k in arrays.keys() if k.startswith("axis_")]
    if isinstance(data, np.ndarray):
        ndim = int(data.ndim)
        preview = _build_preview_payload(data, _extract_npz_axes(arrays, ndim))

    meta = {
        "path": "npz->npz",
        "array_keys": list(arrays.keys()),
        "shapes": shapes,
        "dtypes": dtypes,
        "meta_json_preview": meta_json_preview,
        "message": "NPZ round-trip test completed.",
        "ndim": ndim,
        "shape": list(data.shape) if isinstance(data, np.ndarray) else None,
        "dtype": str(data.dtype) if isinstance(data, np.ndarray) else None,
        "axis_keys": axis_keys,
        "preview": preview,
    }
    return output_bytes, meta


def _convert_itx_to_npz(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    text = input_bytes.decode("utf-8", errors="ignore")
    lines = text.splitlines(keepends=True)

    dim_tokens = _parse_itx_dim_tokens(lines)
    max_row = _compute_itx_data_rows(lines, dim_tokens)
    mat = _load_itx_data_array(text, max_row, dim_tokens)

    axes_meta, axis_arrays = _parse_itx_axes(lines, max_row, dim_tokens)

    ndim = int(mat.ndim)

    if ndim == 2:
        if "axis_0" in axis_arrays and "axis_1" in axis_arrays:
            axis_arrays["axis_0"], axis_arrays["axis_1"] = axis_arrays["axis_1"], axis_arrays["axis_0"]
        if "axis_0_meta" in axes_meta and "axis_1_meta" in axes_meta:
            axes_meta["axis_0_meta"], axes_meta["axis_1_meta"] = axes_meta["axis_1_meta"], axes_meta["axis_0_meta"]
    
    # fallback: 至少保证保存索引轴
    if ndim >= 1 and "axis_0" not in axis_arrays:
        axis_arrays["axis_0"] = np.arange(mat.shape[0], dtype=np.float32)
    if ndim >= 2 and "axis_1" not in axis_arrays:
        axis_arrays["axis_1"] = np.arange(mat.shape[1], dtype=np.float32)
    if ndim >= 3 and "axis_2" not in axis_arrays:
        axis_arrays["axis_2"] = np.arange(mat.shape[2], dtype=np.float32)
    
    axis_labels = options.get("axis_labels", [])
    axis_units = options.get("axis_units", [])
    metadata_mode = options.get("metadata_mode", "preserve")
    experiment_date = options.get("experiment_date", "")
    measurement_datetime = options.get("measurement_datetime", "")
    location = options.get("location", "")
    hv = options.get("hv", "")
    slit = options.get("slit", "")
    sample_name = options.get("sample_name", "")
    operator = options.get("operator", "")
    temperature_K = options.get("temperature_K", "")
    photon_energy_eV = options.get("photon_energy_eV", "")
    bias_voltage_V = options.get("bias_voltage_V", "")
    polarization = options.get("polarization", "")
    notes = options.get("notes", "")
    custom_metadata = options.get("custom_metadata", {}) or {}

    ndim = int(mat.ndim)

    # 若用户没有手动提供 axis_labels，则优先给出默认名
    if not axis_labels:
        axis_labels = [f"axis_{i}" for i in range(ndim)]

    meta_dict = _build_meta_dict(
        source_format="itx",
        data=mat,
        axis_labels=axis_labels,
        axis_units=axis_units,
        metadata_mode=metadata_mode,
        experiment_date=experiment_date,
        measurement_datetime=measurement_datetime,
        location=location,
        hv=hv,
        slit=slit,
        sample_name=sample_name,
        operator=operator,
        temperature_K=temperature_K,
        photon_energy_eV=photon_energy_eV,
        bias_voltage_V=bias_voltage_V,
        polarization=polarization,
        notes=notes,
        custom_metadata=custom_metadata,
        extra={
            "is_complex": bool(np.iscomplexobj(mat)),
            "itx_info": {
                "dim_tokens": dim_tokens,
                "max_row": int(max_row),
                "axes_meta": axes_meta,
            },
        },
    )

    arrays_to_save = {
        "data": mat,
        "meta_json": _meta_json_array(meta_dict),
    }

    for key, value in axis_arrays.items():
        arrays_to_save[key] = value

    output_bytes = _save_npz_bytes(**arrays_to_save)

    axis_keys = [k for k in axis_arrays.keys() if k.startswith("axis_")]
    axes_for_preview = _extract_npz_axes(arrays_to_save, ndim)

    meta = {
        "path": "itx->npz",
        "message": "ITX parsed successfully and saved as NPZ.",
        "shape": list(mat.shape),
        "dtype": str(mat.dtype),
        "ndim": ndim,
        "axis_keys": axis_keys,
        "metadata_mode": metadata_mode,
        "meta_json_preview": meta_dict,
        "preview": _build_preview_payload(mat, axes_for_preview),
        "debug_version": "CONVERTER_PY_ITX_TO_NPZ_ENABLED",
    }

    return output_bytes, meta


def _convert_ibw_to_npz(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    mat, axes, ibw_info = _ibw_bytes_to_array_and_axes(input_bytes)

    axis_labels = options.get("axis_labels", [])
    axis_units = options.get("axis_units", [])
    metadata_mode = options.get("metadata_mode", "preserve")
    experiment_date = options.get("experiment_date", "")
    measurement_datetime = options.get("measurement_datetime", "")
    location = options.get("location", "")
    hv = options.get("hv", "")
    slit = options.get("slit", "")
    sample_name = options.get("sample_name", "")
    operator = options.get("operator", "")
    temperature_K = options.get("temperature_K", "")
    photon_energy_eV = options.get("photon_energy_eV", "")
    bias_voltage_V = options.get("bias_voltage_V", "")
    polarization = options.get("polarization", "")
    notes = options.get("notes", "")
    custom_metadata = options.get("custom_metadata", {}) or {}

    ndim = int(mat.ndim)

    meta_dict = _build_meta_dict(
        source_format="ibw",
        data=mat,
        axis_labels=axis_labels,
        axis_units=axis_units,
        metadata_mode=metadata_mode,
        experiment_date=experiment_date,
        measurement_datetime=measurement_datetime,
        location=location,
        hv=hv,
        slit=slit,
        sample_name=sample_name,
        operator=operator,
        temperature_K=temperature_K,
        photon_energy_eV=photon_energy_eV,
        bias_voltage_V=bias_voltage_V,
        polarization=polarization,
        notes=notes,
        custom_metadata=custom_metadata,
        extra={
            "is_complex": bool(np.iscomplexobj(mat)),
            "ibw_info": ibw_info,
        },
    )

    arrays_to_save = {
        "data": mat,
        "meta_json": _meta_json_array(meta_dict),
    }

    for i, axis in enumerate(axes):
        arrays_to_save[f"axis_{i}"] = axis

    output_bytes = _save_npz_bytes(**arrays_to_save)

    meta = {
        "path": "ibw->npz",
        "message": "IBW parsed successfully and saved as NPZ.",
        "shape": list(mat.shape),
        "dtype": str(mat.dtype),
        "ndim": ndim,
        "axis_keys": [f"axis_{i}" for i in range(len(axes))],
        "metadata_mode": metadata_mode,
        "meta_json_preview": meta_dict,
        "preview": _build_preview_payload(mat, axes),
        "debug_version": "CONVERTER_PY_WITH_META_JSON_AND_PREVIEW",
    }

    return output_bytes, meta


def _convert_npz_to_itx(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    raise NotImplementedError("NPZ -> ITX is not connected yet.")


def _convert_npz_to_ibw(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    raise NotImplementedError("NPZ -> IBW is not connected yet.")

def _convert_pxt_to_npz(input_bytes: bytes, options: Dict[str, Any]):
    header = _parse_ses_text_header_from_pxt(input_bytes)

    y_num, e_num, y_axis, e_axis = _ses_header_to_dims_and_axes(header, input_bytes)
    mat = _read_ses_pxt_matrix(input_bytes, y_num, e_num)

    axes = [y_axis, e_axis]

    arrays_to_save = {
        "data": np.asarray(mat, dtype=np.float32),
        "axis_0": y_axis,
        "axis_1": e_axis,
    }

    meta_dict = _build_meta_dict(
        source_format="pxt",
        data=mat,
        axis_labels=["Y", "Ek"],
        axis_units=["channel", "eV"],
        metadata_mode=options.get("metadata_mode", "preserve"),
        experiment_date="",
        measurement_datetime="",
        location="",
        hv=header.get("Excitation Energy", ""),
        slit="",
        sample_name=header.get("Sample", ""),
        operator=header.get("User", ""),
        temperature_K="",
        photon_energy_eV=header.get("Excitation Energy", ""),
        bias_voltage_V="",
        polarization="",
        notes=header.get("Comments", ""),
        custom_metadata={},
        extra={
            "pxt_info": header
        },
    )

    arrays_to_save["meta_json"] = _meta_json_array(meta_dict)
    output_bytes = _save_npz_bytes(**arrays_to_save)

    meta = {
        "path": "pxt->npz",
        "message": "PXT parsed successfully as SES binary + ASCII header.",
        "shape": list(mat.shape),
        "dtype": str(mat.dtype),
        "ndim": 2,
        "axis_keys": ["axis_0", "axis_1"],
        "preview": _build_preview_payload(mat, axes),
    }

    return output_bytes, meta

def _convert_da30_zip_to_npz(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    mat, axes, da30_info = _da30_parse_bundle(input_bytes)

    axis_labels = options.get("axis_labels", [])
    axis_units = options.get("axis_units", [])
    metadata_mode = options.get("metadata_mode", "preserve")
    experiment_date = options.get("experiment_date", "")
    measurement_datetime = options.get("measurement_datetime", "")
    location = options.get("location", "")
    hv = options.get("hv", "")
    slit = options.get("slit", "")
    sample_name = options.get("sample_name", "")
    operator = options.get("operator", "")
    temperature_K = options.get("temperature_K", "")
    photon_energy_eV = options.get("photon_energy_eV", "")
    bias_voltage_V = options.get("bias_voltage_V", "")
    polarization = options.get("polarization", "")
    notes = options.get("notes", "")
    custom_metadata = options.get("custom_metadata", {}) or {}

    ndim = int(mat.ndim)

    # 默认使用 DA30 的物理维度名，顺序与 data shape 一致: (Theta, Phi, Ek)
    if not axis_labels:
        viewer_ini = da30_info.get("viewer_ini", {})
        axis_labels = [
            str(viewer_ini.get("theta_label") or "Theta"),
            str(viewer_ini.get("phi_label") or "Phi"),
            str(viewer_ini.get("e_label") or "Ek"),
        ]

    meta_dict = _build_meta_dict(
        source_format="da30_zip",
        data=mat,
        axis_labels=axis_labels,
        axis_units=axis_units,
        metadata_mode=metadata_mode,
        experiment_date=experiment_date or da30_info["region_info"].get("Date", ""),
        measurement_datetime=measurement_datetime or da30_info["region_info"].get("Time", ""),
        location=location or da30_info["region_info"].get("Location", ""),
        hv=hv,
        slit=slit,
        sample_name=sample_name or da30_info["region_info"].get("Sample", ""),
        operator=operator or da30_info["region_info"].get("User", ""),
        temperature_K=temperature_K,
        photon_energy_eV=photon_energy_eV,
        bias_voltage_V=bias_voltage_V,
        polarization=polarization,
        notes=notes,
        custom_metadata=custom_metadata,
        extra={
            "is_complex": False,
            "da30_info": da30_info,
        },
    )

    arrays_to_save = {
        "data": mat,
        "axis_0": np.asarray(axes[0], dtype=np.float32),
        "axis_1": np.asarray(axes[1], dtype=np.float32),
        "axis_2": np.asarray(axes[2], dtype=np.float32),
        "meta_json": _meta_json_array(meta_dict),
    }

    output_bytes = _save_npz_bytes(**arrays_to_save)

    meta = {
        "path": "da30_zip->npz",
        "message": "DA30 ZIP parsed successfully and saved as NPZ.",
        "shape": list(mat.shape),
        "dtype": str(mat.dtype),
        "ndim": ndim,
        "axis_keys": ["axis_0", "axis_1", "axis_2"],
        "metadata_mode": metadata_mode,
        "meta_json_preview": meta_dict,
        "preview": _build_preview_payload(mat, axes),
    }

    return output_bytes, meta



def _convert_xarray_to_npz(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    raise NotImplementedError("XARRAY -> NPZ is not connected yet.")


def _convert_npz_to_xarray(input_bytes: bytes, options: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    import xarray as xr

    arrays = _load_npz_bytes(input_bytes)

    if "data" not in arrays:
        raise ValueError("NPZ must contain a 'data' array.")

    data = arrays["data"]
    ndim = int(data.ndim)
    shape = list(data.shape)

    # -------------------------
    # 1. 读取 meta_json（如果有）
    # -------------------------
    meta_dict = {}
    if "meta_json" in arrays:
        raw = _safe_scalar_from_npz_value(arrays["meta_json"])
        try:
            meta_dict = json.loads(raw)
        except Exception:
            meta_dict = {}

    axis_labels = meta_dict.get("axis_labels", []) if isinstance(meta_dict, dict) else []
    axis_units = meta_dict.get("axis_units", []) if isinstance(meta_dict, dict) else []

    # -------------------------
    # 2. 构建 dims
    # -------------------------
    dims = []
    for i in range(ndim):
        if i < len(axis_labels) and axis_labels[i]:
            dims.append(str(axis_labels[i]))
        else:
            dims.append(f"axis_{i}")

    # -------------------------
    # 3. 构建 coords
    # -------------------------
    coords = {}
    axes = _extract_npz_axes(arrays, ndim)

    for i in range(ndim):
        dim = dims[i]

        if i < len(axes) and axes[i].shape[0] == shape[i]:
            coord = axes[i]
        else:
            coord = np.arange(shape[i])

        coords[dim] = coord

    # -------------------------
    # 4. 构建 DataArray
    # -------------------------
    da = xr.DataArray(
        data=data,
        dims=dims,
        coords=coords,
        name="data",
    )

    # -------------------------
    # 5. 写入 axis 单位
    # -------------------------
    for i, dim in enumerate(dims):
        if i < len(axis_units) and axis_units[i]:
            da.coords[dim].attrs["unit"] = axis_units[i]

    # -------------------------
    # 6. 写入 attrs（去掉 axis 信息）
    # -------------------------
    if isinstance(meta_dict, dict):
        for key, value in meta_dict.items():
            if key not in ("axis_labels", "axis_units"):
                da.attrs[key] = _to_netcdf_safe_attr(value)

    # -------------------------
    # 7. 导出 NetCDF（bytes）
    # -------------------------
    nc_bytes = da.to_netcdf()

    # -------------------------
    # 8. preview（复用现有逻辑）
    # -------------------------
    preview = _build_preview_payload(data, axes)

    meta = {
        "path": "npz->xarray",
        "message": "NPZ successfully converted to xarray NetCDF.",
        "shape": shape,
        "dtype": str(data.dtype),
        "ndim": ndim,
        "dims": dims,
        "coords": list(coords.keys()),
        "preview": preview,
    }

    return nc_bytes, meta


# -----------------------------
# Dispatcher
# -----------------------------

def convert_bytes(
    input_bytes: bytes,
    input_format: str,
    output_format: str,
    options: Dict[str, Any] | None = None,
):
    options = _normalize_options(options)
    path = f"{input_format}->{output_format}"

    dispatch = {
        "npz->npz": _convert_npz_to_npz,
        "itx->npz": _convert_itx_to_npz,
        "ibw->npz": _convert_ibw_to_npz,
        "npz->itx": _convert_npz_to_itx,
        "npz->ibw": _convert_npz_to_ibw,
        "da30_zip->npz": _convert_da30_zip_to_npz,
        "xarray->npz": _convert_xarray_to_npz,
        "npz->xarray": _convert_npz_to_xarray,
        "pxt->npz": _convert_pxt_to_npz,
    }

    if path not in dispatch:
        error = ValueError(f"Unsupported conversion path: {path}")
        return b"", _error_meta(input_format, output_format, len(input_bytes), error)

    try:
        output_bytes, inner_meta = dispatch[path](input_bytes, options)
        meta = _ok_meta(
            input_format=input_format,
            output_format=output_format,
            input_size_bytes=len(input_bytes),
            extra=inner_meta,
        )
        return output_bytes, meta

    except Exception as error:
        return b"", _error_meta(input_format, output_format, len(input_bytes), error)

def _preview_pxt(input_bytes: bytes, options: Dict[str, Any]) -> Dict[str, Any]:
    header = _parse_ses_text_header_from_pxt(input_bytes)
    y_num, e_num, y_axis, e_axis = _ses_header_to_dims_and_axes(header, input_bytes)
    mat = _read_ses_pxt_matrix(input_bytes, y_num, e_num)

    axes = [y_axis, e_axis]

    return {
        "path": "pxt::preview",
        "message": "PXT preview generated successfully.",
        "shape": list(mat.shape),
        "dtype": str(mat.dtype),
        "ndim": int(mat.ndim),
        "axis_keys": ["axis_0", "axis_1"],
        "preview": _build_preview_payload(mat, axes),
        "pxt_info": {
            "header": header,
        },
    }

def _preview_itx(input_bytes: bytes, options: Dict[str, Any]) -> Dict[str, Any]:
    text = input_bytes.decode("utf-8", errors="ignore")
    lines = text.splitlines(keepends=True)

    dim_tokens = _parse_itx_dim_tokens(lines)
    max_row = _compute_itx_data_rows(lines, dim_tokens)
    mat = _load_itx_data_array(text, max_row, dim_tokens)

    axes_meta, axis_arrays = _parse_itx_axes(lines, max_row, dim_tokens)
    ndim = int(mat.ndim)

    if ndim == 2:
        if "axis_0" in axis_arrays and "axis_1" in axis_arrays:
            axis_arrays["axis_0"], axis_arrays["axis_1"] = axis_arrays["axis_1"], axis_arrays["axis_0"]
        if "axis_0_meta" in axes_meta and "axis_1_meta" in axes_meta:
            axes_meta["axis_0_meta"], axes_meta["axis_1_meta"] = axes_meta["axis_1_meta"], axes_meta["axis_0_meta"]

    # 和 convert 路径保持一致：至少补索引轴
    if ndim >= 1 and "axis_0" not in axis_arrays:
        axis_arrays["axis_0"] = np.arange(mat.shape[0], dtype=np.float32)
    if ndim >= 2 and "axis_1" not in axis_arrays:
        axis_arrays["axis_1"] = np.arange(mat.shape[1], dtype=np.float32)
    if ndim >= 3 and "axis_2" not in axis_arrays:
        axis_arrays["axis_2"] = np.arange(mat.shape[2], dtype=np.float32)

    axis_keys = [k for k in axis_arrays.keys() if k.startswith("axis_")]
    axes = _extract_npz_axes(axis_arrays, ndim)

    return {
        "path": "itx::preview",
        "message": "ITX preview generated successfully.",
        "shape": list(mat.shape),
        "dtype": str(mat.dtype),
        "ndim": ndim,
        "axis_keys": axis_keys,
        "preview": _build_preview_payload(mat, axes),
        "itx_info": {
            "dim_tokens": dim_tokens,
            "max_row": int(max_row),
            "axes_meta": axes_meta,
        },
    }

def _preview_ibw(input_bytes: bytes, options: Dict[str, Any]) -> Dict[str, Any]:
    mat, axes, ibw_info = _ibw_bytes_to_array_and_axes(input_bytes)
    return {
        "path": "ibw::preview",
        "message": "IBW preview generated successfully.",
        "shape": list(mat.shape),
        "dtype": str(mat.dtype),
        "ndim": int(mat.ndim),
        "axis_keys": [f"axis_{i}" for i in range(len(axes))],
        "preview": _build_preview_payload(mat, axes),
        "ibw_info": ibw_info,
    }


def _preview_npz(input_bytes: bytes, options: Dict[str, Any]) -> Dict[str, Any]:
    arrays = _load_npz_bytes(input_bytes)
    data = arrays.get("data")
    if not isinstance(data, np.ndarray):
        raise ValueError("NPZ preview requires a 'data' array.")

    ndim = int(data.ndim)
    axis_keys = [k for k in arrays.keys() if k.startswith("axis_")]
    axes = _extract_npz_axes(arrays, ndim)

    return {
        "path": "npz::preview",
        "message": "NPZ preview generated successfully.",
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "ndim": ndim,
        "axis_keys": axis_keys,
        "preview": _build_preview_payload(data, axes),
    }


def preview_bytes(
    input_bytes: bytes,
    input_format: str,
    options: Dict[str, Any] | None = None,
):
    options = _normalize_options(options)

    dispatch = {
        "itx": _preview_itx,
        "ibw": _preview_ibw,
        "pxt": _preview_pxt,
        "npz": _preview_npz,
        
    }

    if input_format not in dispatch:
        error = ValueError(f"Preview is not supported for input format: {input_format}")
        return _error_meta(input_format, "preview", len(input_bytes), error)

    try:
        inner_meta = dispatch[input_format](input_bytes, options)
        return _ok_meta(
            input_format=input_format,
            output_format="preview",
            input_size_bytes=len(input_bytes),
            extra=inner_meta,
        )
    except Exception as error:
        return _error_meta(input_format, "preview", len(input_bytes), error)

def _to_netcdf_safe_attr(value):
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return value
    if isinstance(value, np.ndarray):
        return value
    if isinstance(value, (list, tuple)):
        try:
            return np.asarray(value)
        except Exception:
            return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)