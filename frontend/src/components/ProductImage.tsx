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
    return <div className={large ? "thumb-lg-missing" : "thumb-missing"}>No image</div>;
  }
  return (
    <img
      className={large ? "thumb-lg" : "thumb"}
      src={src}
      alt={alt}
      onError={() => setFailed(true)}
    />
  );
}
