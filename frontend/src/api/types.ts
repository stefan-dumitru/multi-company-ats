/** One page of a list, as every list endpoint of the API answers (see backend app/pagination.py). */
export interface Page<Item> {
  items: Item[]
  total: number
  page: number
  page_size: number
}
