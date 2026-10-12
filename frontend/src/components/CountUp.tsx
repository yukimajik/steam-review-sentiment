import { useCountUp } from '../motion'

/** A number that counts up when it first appears. Screen readers get only the final value. */
export function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const shown = useCountUp(value)
  return (
    <>
      <span aria-hidden="true">{format(shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </>
  )
}
