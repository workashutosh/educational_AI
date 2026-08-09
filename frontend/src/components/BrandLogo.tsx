import { Link } from "react-router-dom"

import logoUrl from "@/assets/logo.png"
import { cn } from "@/lib/utils"

type BrandLogoProps = {
  /** Show the ClassKit wordmark next to the mark */
  withWordmark?: boolean
  /** Link to home when set (pass `false` to disable) */
  to?: string | false
  className?: string
  /** Pixel size of the square mark */
  size?: number
  wordmarkClassName?: string
}

export function BrandLogo({
  withWordmark = true,
  to = "/",
  className,
  size = 28,
  wordmarkClassName,
}: BrandLogoProps) {
  const mark = (
    <img
      src={logoUrl}
      alt=""
      width={size}
      height={size}
      className="shrink-0 object-contain"
      style={{ width: size, height: size }}
      decoding="async"
    />
  )

  const content = (
    <span
      className={cn(
        "inline-flex items-center gap-2 font-display tracking-tight text-foreground",
        className,
      )}
    >
      {mark}
      {withWordmark ? (
        <span className={cn("leading-none", wordmarkClassName)}>ClassKit</span>
      ) : (
        <span className="sr-only">ClassKit</span>
      )}
    </span>
  )

  if (to === false) {
    return content
  }

  return (
    <Link to={to} className="inline-flex items-center" title="ClassKit">
      {content}
    </Link>
  )
}
