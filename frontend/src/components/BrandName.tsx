// "SRA" and "scout" get contrasting colours so both halves of the name read at a glance.
// `onDark` switches to lighter shades for the dark header.
export default function BrandName({ onDark = false }: { onDark?: boolean }) {
  return (
    <span className="tracking-tight">
      <span className={`font-extrabold ${onDark ? 'text-[#69b1ff]' : 'text-[#1677ff]'}`}>SRA</span>
      <span className={`font-semibold ${onDark ? 'text-[#95de64]' : 'text-[#389e0d]'}`}>scout</span>
    </span>
  )
}
