# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, Union, Literal

# Pillow
from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError


logger = logging.getLogger(__name__)


@dataclass
class CompressResult:
    data: bytes
    format: str
    width: int
    height: int
    original_bytes: int
    compressed_bytes: int

    @property
    def ratio_percent(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return (self.compressed_bytes / self.original_bytes) * 100.0


class ImageCompressor:
    """
    本地图片压缩器：输入 bytes -> 输出压缩后的 bytes 或 base64 字符串

    设计目标：
    - 稳定：处理 EXIF 旋转、截断文件、超大图（decompression bomb）、未知格式、透明 PNG、动图等
    - 高效：可选使用 pyvips（libvips）后端；否则使用 Pillow
    - 可控：max_size / quality / max_bytes / alpha 策略 / 输出格式策略

    依赖：
    - 必需：Pillow
    - 可选更快：pyvips（需要系统安装 libvips）

    备选API方案：
    https://tinypng.com/developers/reference
    """

    def __init__(
        self,
        *,
        max_size: Tuple[int, int] = (768, 768),
        quality: int = 85,
        max_bytes: Optional[int] = None,
        # prefer: "auto" 会根据透明度/格式智能选 PNG/JPEG；也可强制 "jpeg" 或 "png"
        prefer_format: Literal["auto", "jpeg", "png"] = "auto",
        # PNG 有透明度时怎么处理：keep=保留 PNG；flatten=铺白底转 JPEG（通常更小更适合 GPT）
        alpha_mode: Literal["keep", "flatten"] = "flatten",
        # JPEG 最低质量下限（用于 max_bytes 目标压缩时递减 quality）
        min_quality: int = 45,
        # 如果图片特别大（像素过多）就拒绝，避免解压炸弹/内存爆
        max_pixels: int = 60_000_000,  # 6000万像素，按你服务能力调
        # Pillow 容错：允许加载截断图片（更“稳”）
        allow_truncated: bool = True,
        # 是否尝试使用 pyvips
        enable_pyvips: bool = True,
    ):
        self.max_size = max_size
        self.quality = int(quality)
        self.max_bytes = max_bytes
        self.prefer_format = prefer_format
        self.alpha_mode = alpha_mode
        self.min_quality = int(min_quality)
        self.max_pixels = int(max_pixels)
        self.allow_truncated = bool(allow_truncated)

        self._pyvips = None
        if enable_pyvips:
            try:
                import pyvips  # type: ignore
                self._pyvips = pyvips
            except Exception:
                self._pyvips = None

        # Pillow 全局容错设置
        ImageFile.LOAD_TRUNCATED_IMAGES = self.allow_truncated
        # 避免 decompression bomb（你也可以改为更严格）
        Image.MAX_IMAGE_PIXELS = self.max_pixels

    def compress(
        self,
        image_bytes: bytes,
        *,
        enable_base64: bool = False,
        max_size: Optional[Tuple[int, int]] = None,
        quality: Optional[int] = None,
        max_bytes: Optional[int] = None,
        prefer_format: Optional[Literal["auto", "jpeg", "png"]] = None,
        alpha_mode: Optional[Literal["keep", "flatten"]] = None,
        return_result: bool = False,
    ) -> Union[bytes, str, CompressResult, None]:
        """
        压缩图片 bytes。
        - 返回 bytes / base64 str（取决于 enable_base64）
        - return_result=True 时返回 CompressResult（包含尺寸/压缩率/格式等）
        """
        if not image_bytes or not isinstance(image_bytes, (bytes, bytearray)):
            return None

        max_size = max_size or self.max_size
        quality = int(quality if quality is not None else self.quality)
        max_bytes = max_bytes if max_bytes is not None else self.max_bytes
        prefer_format = prefer_format or self.prefer_format
        alpha_mode = alpha_mode or self.alpha_mode

        original_len = len(image_bytes)

        # 更快后端：pyvips（如果可用）
        if self._pyvips is not None:
            try:
                res = self._compress_with_pyvips(
                    image_bytes=image_bytes,
                    max_size=max_size,
                    quality=quality,
                    max_bytes=max_bytes,
                    prefer_format=prefer_format,
                    alpha_mode=alpha_mode,
                )
                if res is None:
                    return None
                return self._finalize_output(res, enable_base64, return_result)
            except Exception:
                # 回退到 pillow
                logger.debug("pyvips compress failed, fallback to pillow.", exc_info=True)

        # 通用后端：Pillow
        try:
            res = self._compress_with_pillow(
                image_bytes=image_bytes,
                max_size=max_size,
                quality=quality,
                max_bytes=max_bytes,
                prefer_format=prefer_format,
                alpha_mode=alpha_mode,
            )
            if res is None:
                return None
            return self._finalize_output(res, enable_base64, return_result)
        except Exception:
            logger.exception("Image compress failed.")
            return None

    def _finalize_output(
        self,
        res: CompressResult,
        enable_base64: bool,
        return_result: bool,
    ) -> Union[bytes, str, CompressResult]:
        if return_result:
            return res
        if enable_base64:
            return base64.b64encode(res.data).decode("utf-8")
        return res.data

    # -----------------------------
    # Pillow backend
    # -----------------------------
    def _compress_with_pillow(
        self,
        *,
        image_bytes: bytes,
        max_size: Tuple[int, int],
        quality: int,
        max_bytes: Optional[int],
        prefer_format: Literal["auto", "jpeg", "png"],
        alpha_mode: Literal["keep", "flatten"],
    ) -> Optional[CompressResult]:
        bio = io.BytesIO(image_bytes)

        try:
            img = Image.open(bio)
        except UnidentifiedImageError:
            return None

        # verify 会把文件读到末尾，且之后不能继续操作同一个对象
        # 这里用更稳的方式：先 load 一遍 + 捕获异常即可
        try:
            img.load()
        except Exception:
            # 截断/坏图可能在 load 时抛错
            if not self.allow_truncated:
                return None

        original_format = (img.format or "").upper()

        # EXIF 方向纠正（手机图很常见）
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # 动图处理：只取第一帧（GIF/WebP/PNG APNG 等）
        # Pillow 对 is_animated 支持取决于格式插件
        try:
            if getattr(img, "is_animated", False):
                img.seek(0)
        except Exception:
            pass

        # 像素上限（双保险：即使 Pillow 的 MAX_IMAGE_PIXELS 没拦住，也这里拦）
        w, h = img.size
        if w <= 0 or h <= 0:
            return None
        if (w * h) > self.max_pixels:
            logger.warning("Image too large in pixels: %sx%s", w, h)
            return None

        # 选择输出格式策略
        has_alpha = self._pillow_has_alpha(img)

        out_format = self._choose_output_format(
            prefer_format=prefer_format,
            original_format=original_format,
            has_alpha=has_alpha,
            alpha_mode=alpha_mode,
        )

        # 模式转换
        if out_format == "JPEG":
            img = self._to_rgb_for_jpeg(img, alpha_mode=alpha_mode)
        elif out_format == "PNG":
            # PNG 保持 RGBA/LA 或 RGB 均可
            pass

        # resize（thumbnail 等比缩放，且更稳）
        if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # 首次编码
        encoded = self._pillow_encode(img, out_format=out_format, quality=quality)

        # 如果要求 max_bytes，则递减质量（JPEG）或优化 PNG（量化/压缩级别）
        if max_bytes is not None and len(encoded) > max_bytes:
            encoded, out_format = self._shrink_to_target(
                img=img,
                first_encoded=encoded,
                out_format=out_format,
                quality=quality,
                max_bytes=max_bytes,
            )

        res = CompressResult(
            data=encoded,
            format=out_format,
            width=img.size[0],
            height=img.size[1],
            original_bytes=len(image_bytes),
            compressed_bytes=len(encoded),
        )

        try:
            img.close()
        except Exception:
            pass

        return res

    def _pillow_encode(self, img: Image.Image, *, out_format: str, quality: int) -> bytes:
        out = io.BytesIO()
        if out_format == "JPEG":
            # progressive + optimize 通常更小；subsampling 4:2:0 也会更小
            img.save(
                out,
                format="JPEG",
                quality=max(1, min(quality, 95)),
                optimize=True,
                progressive=True,
                subsampling="4:2:0",
            )
        elif out_format == "PNG":
            # compress_level 0-9；optimize=True 会额外尝试优化
            img.save(
                out,
                format="PNG",
                optimize=True,
                compress_level=6,
            )
        else:
            # 理论不会到这
            img.save(out, format="JPEG", quality=max(1, min(quality, 95)), optimize=True)
        return out.getvalue()

    def _shrink_to_target(
        self,
        *,
        img: Image.Image,
        first_encoded: bytes,
        out_format: str,
        quality: int,
        max_bytes: int,
    ) -> Tuple[bytes, str]:
        # 1) JPEG：逐步降质量
        if out_format == "JPEG":
            q = quality
            best = first_encoded
            while len(best) > max_bytes and q > self.min_quality:
                q = max(self.min_quality, q - 8)
                candidate = self._pillow_encode(img, out_format="JPEG", quality=q)
                # 如果变大了（少见，但可能发生），就停
                if len(candidate) >= len(best):
                    break
                best = candidate
            return best, "JPEG"

        # 2) PNG：如果太大，尝试量化（把真彩转索引色），通常能大幅减小
        if out_format == "PNG":
            try:
                # 对 RGBA 量化时，先合成到白底再量化，效果更稳
                base = img
                if self._pillow_has_alpha(img):
                    base = self._to_rgb_for_jpeg(img, alpha_mode="flatten")
                # quantize 到 256 色（可调到 128 更小，但可能更糊）
                qimg = base.quantize(method=Image.Quantize.MEDIANCUT, colors=256)
                # 保存为 PNG
                out = io.BytesIO()
                qimg.save(out, format="PNG", optimize=True, compress_level=9)
                candidate = out.getvalue()
                if len(candidate) < len(first_encoded):
                    return candidate, "PNG"
            except Exception:
                pass

        # 兜底：返回首次编码
        return first_encoded, out_format

    def _choose_output_format(
        self,
        *,
        prefer_format: Literal["auto", "jpeg", "png"],
        original_format: str,
        has_alpha: bool,
        alpha_mode: Literal["keep", "flatten"],
    ) -> str:
        if prefer_format == "jpeg":
            return "JPEG"
        if prefer_format == "png":
            return "PNG"

        # auto：
        # - 有透明度：keep -> PNG；flatten -> JPEG
        # - 无透明度：默认 JPEG（通常体积更小，且 GPT 识别没差）
        if has_alpha:
            return "PNG" if alpha_mode == "keep" else "JPEG"

        # 原本就是 PNG 也不一定要保留；无透明时 JPEG 通常更省
        return "JPEG"

    def _pillow_has_alpha(self, img: Image.Image) -> bool:
        if img.mode in ("RGBA", "LA"):
            return True
        # P 模式带透明
        if img.mode == "P" and "transparency" in img.info:
            return True
        return False

    def _to_rgb_for_jpeg(self, img: Image.Image, *, alpha_mode: Literal["keep", "flatten"]) -> Image.Image:
        # JPEG 不支持 alpha，默认 flatten 到白底
        if self._pillow_has_alpha(img):
            if alpha_mode == "flatten":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[-1])
                elif img.mode == "LA":
                    bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                else:
                    # 其他情况尽力转
                    bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                try:
                    img.close()
                except Exception:
                    pass
                return bg
            # keep 但又要 JPEG：只能 flatten
            return img.convert("RGB")
        # 无 alpha 直接转 RGB
        if img.mode != "RGB":
            return img.convert("RGB")
        return img

    # -----------------------------
    # pyvips backend (optional)
    # -----------------------------
    def _compress_with_pyvips(
        self,
        *,
        image_bytes: bytes,
        max_size: Tuple[int, int],
        quality: int,
        max_bytes: Optional[int],
        prefer_format: Literal["auto", "jpeg", "png"],
        alpha_mode: Literal["keep", "flatten"],
    ) -> Optional[CompressResult]:
        pyvips = self._pyvips
        if pyvips is None:
            return None

        # access="sequential" 更省内存；fail=True 遇到坏图直接失败
        img = pyvips.Image.new_from_buffer(image_bytes, "", access="sequential", fail=True)

        # 尺寸检查
        w = int(img.width)
        h = int(img.height)
        if w <= 0 or h <= 0:
            return None
        if (w * h) > self.max_pixels:
            logger.warning("Image too large in pixels: %sx%s", w, h)
            return None

        # 动图：libvips 通常只读第一页/第一帧（对我们的用途正好）
        # EXIF 方向
        try:
            img = img.autorot()
        except Exception:
            pass

        # resize: 保持比例
        max_w, max_h = max_size
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            img = img.resize(scale, kernel="lanczos3")
            w = int(img.width)
            h = int(img.height)

        has_alpha = img.hasalpha() if hasattr(img, "hasalpha") else False

        out_format = self._choose_output_format(
            prefer_format=prefer_format,
            original_format="",  # vips 不可靠提供原格式
            has_alpha=has_alpha,
            alpha_mode=alpha_mode,
        )

        if out_format == "JPEG":
            # flatten alpha
            if has_alpha:
                # 白底合成
                img = img.flatten(background=[255, 255, 255])
            # 保证三通道
            if img.bands > 3:
                img = img.extract_band(0, n=3)

            buf = img.jpegsave_buffer(
                Q=max(1, min(quality, 95)),
                optimize_coding=True,
                interlace=True,  # progressive
                subsample_mode="on",
            )

            # 目标体积：递减 Q
            if max_bytes is not None and len(buf) > max_bytes:
                q = quality
                best = buf
                while len(best) > max_bytes and q > self.min_quality:
                    q = max(self.min_quality, q - 8)
                    cand = img.jpegsave_buffer(
                        Q=max(1, min(q, 95)),
                        optimize_coding=True,
                        interlace=True,
                        subsample_mode="on",
                    )
                    if len(cand) >= len(best):
                        break
                    best = cand
                buf = best

            return CompressResult(
                data=bytes(buf),
                format="JPEG",
                width=w,
                height=h,
                original_bytes=len(image_bytes),
                compressed_bytes=len(buf),
            )

        # PNG
        # alpha_mode=flatten 且 prefer=auto 时走 JPEG；到这里一般是 keep
        buf = img.pngsave_buffer(compression=6, filter=pyvips.ForeignPngFilter.NONE)

        # PNG 目标体积：尽力加压缩/滤波（libvips 的 pngsave 参数有限）
        if max_bytes is not None and len(buf) > max_bytes:
            buf2 = img.pngsave_buffer(compression=9, filter=pyvips.ForeignPngFilter.ADAPTIVE)
            if len(buf2) < len(buf):
                buf = buf2

        return CompressResult(
            data=bytes(buf),
            format="PNG",
            width=w,
            height=h,
            original_bytes=len(image_bytes),
            compressed_bytes=len(buf),
        )
