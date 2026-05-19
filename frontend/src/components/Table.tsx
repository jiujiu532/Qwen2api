interface Column<T> {
  key: string
  header: string
  render?: (row: T) => React.ReactNode
  className?: string
}

interface TableProps<T> {
  columns: Column<T>[]
  data: T[]
  emptyText?: string
}

export function Table<T extends Record<string, any>>({ columns, data, emptyText = "暂无数据" }: TableProps<T>) {
  return (
    <div className="bg-white rounded-[14px] overflow-x-auto">
      <table className="w-full border-collapse min-w-full">
        <thead>
          <tr>
            {columns.map(col => (
              <th key={col.key} className={`text-left text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5 tracking-wide ${col.className || ""}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="text-center text-[13px] text-[#8a8a8a] py-12">
                {emptyText}
              </td>
            </tr>
          ) : (
            data.map((row, i) => (
              <tr key={i} className="hover:bg-[#fdfdfd] transition-colors">
                {columns.map(col => (
                  <td key={col.key} className={`text-[13px] px-4 py-3 align-middle text-[#3f3f3f] ${col.className || ""}`}>
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
