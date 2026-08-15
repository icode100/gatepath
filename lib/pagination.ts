export const QUESTION_BANK_PAGE_SIZE = 50;

export type PaginationItem = number | "ellipsis-start" | "ellipsis-end";

export const paginationPageCount = (total: number, pageSize: number) =>
  Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, pageSize)));

export const clampPaginationPage = (page: number, pageCount: number) =>
  Math.min(Math.max(1, Math.trunc(page) || 1), Math.max(1, pageCount));

export const paginationItems = (
  currentPage: number,
  pageCount: number,
): PaginationItem[] => {
  const lastPage = Math.max(1, pageCount);
  const current = clampPaginationPage(currentPage, lastPage);

  if (lastPage <= 7) {
    return Array.from({ length: lastPage }, (_, index) => index + 1);
  }

  const pages = new Set([1, lastPage]);
  for (let page = current - 1; page <= current + 1; page += 1) {
    if (page > 1 && page < lastPage) pages.add(page);
  }

  const sortedPages = [...pages].sort((a, b) => a - b);
  const items: PaginationItem[] = [];
  sortedPages.forEach((page, index) => {
    const previousPage = sortedPages[index - 1];
    if (previousPage != null && page - previousPage > 1) {
      items.push(previousPage === 1 ? "ellipsis-start" : "ellipsis-end");
    }
    items.push(page);
  });
  return items;
};
