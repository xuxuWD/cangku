/** 分段器（UI v2 §4.2）：`role=tablist` 语义 + 禁用态；样式见 ui.css 的 `.segmented`。 */
export interface SegmentedOption<T extends string> {
  value: T
  label: string
  disabled?: boolean
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  disabled = false,
}: {
  value: T
  options: Array<SegmentedOption<T>>
  onChange: (value: T) => void
  /** 无障碍名称（tablist 必须有名） */
  label: string
  disabled?: boolean
}) {
  return (
    <div className="segmented" role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          disabled={disabled || option.disabled}
          className={option.value === value ? 'is-active' : ''}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}