export interface ErrorDetailItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface ErrorResponse {
  detail: string;
  error_code: string;
  status_code: number;
  timestamp: string;
  errors?: ErrorDetailItem[] | null;
}

