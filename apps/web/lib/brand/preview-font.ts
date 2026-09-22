import "server-only";
import type { PreviewFont } from "@/components/clips/SilentPreview";
import type { BrandProfile, Repo } from "@/lib/repo/types";
import { extensionOf, fontFormat } from "@/lib/brand/assets";

/* Primärfont des Markenprofils (ci.fonts.primary_asset_id, sonst secondary) als @font-face-Quelle für die stumme Vorschau */
export async function previewFontFor(repo: Repo, brand: BrandProfile | null): Promise<PreviewFont | null> {
  if (!brand) return null;
  const id = brand.ci?.fonts?.primary_asset_id ?? brand.ci?.fonts?.secondary_asset_id ?? null;
  if (!id) return null;
  const asset = await repo.getBrandAsset(id);
  if (!asset || asset.kind !== "font" || asset.brand_profile_id !== brand.id) return null;
  return {
    family: asset.font_family ?? asset.name.replace(/\.[a-z0-9]+$/i, ""),
    url: `/api/brand/${brand.id}/assets/${asset.id}`,
    format: fontFormat(extensionOf(asset.storage_key)),
    weight: asset.font_weight,
  };
}
