import { ImageOff } from "lucide-react";
import { useState } from "react";

export function ProductImage({
  src,
  alt,
  large = false,
}: {
  src: string | null | undefined;
  alt: string;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div className={large ? "thumb-lg-missing" : "thumb-missing"}>
        <ImageOff size={large ? 20 : 16} aria-hidden="true" />
        {large ? "No image" : null}
      </div>
    );
  }
  return (
    <img
      className={large ? "thumb-lg" : "thumb"}
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}
