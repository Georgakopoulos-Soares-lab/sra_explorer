// "SRA" and "scout" get contrasting colours so both halves of the name read at a glance.
// `onDark` switches to lighter shades for the dark header.
export default function BrandName({ onDark = false }: { onDark?: boolean }) {
  return (
    <span className="tracking-tight">
      <span className={`font-extrabold ${onDark ? 'text-brand-sra-light' : 'text-brand-sra'}`}>SRA</span>
      <span className={`font-semibold ${onDark ? 'text-brand-scout-light' : 'text-brand-scout'}`}>scout</span>
    </span>
  )
}
